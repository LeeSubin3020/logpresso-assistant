"""
로그프레소 쿼리 생성 + 에러 진단 에이전트 (RAG 기반) - Streamlit 앱

최초 1회: pip install -r requirements.txt 후 학습.bat (인덱스 구축)
실행: 실행.bat 더블클릭 (= python -m streamlit run app.py)
자세한 내용은 사용_가이드.md 참고.
"""

import base64
import io
import os
import re

import anthropic
import streamlit as st
from anthropic import Anthropic
from PIL import Image

from prompts import build_system_prompt
from retriever import retrieve, format_context
from manual_lookup import lookup, format_sections
from logger import log_interaction, load_history

# Opus 5.5: 이미지 긴 변 2576px까지 원본 해상도로 읽음 (Sonnet 4.6은 1568px로 축소돼 작은 글씨가 뭉개짐)
MODEL = "claude-opus-5-5"
EFFORT = "high"  # Opus 5.5 기본값은 medium. 쿼리/진단 정확도 위해 high
# 보안 로그 질문이 안전 분류기에 오탐될 때 같은 요청을 다른 모델로 자동 재시도
FALLBACKS = [{"model": "claude-opus-4-8"}]
FALLBACK_BETA = "server-side-fallback-2026-06-01"
TOP_K = 8
MAX_IMAGE_EDGE = 2576  # 모델이 읽는 최대 해상도(긴 변). 이보다 크면 어차피 서버에서 축소됨
MAX_IMAGE_BYTES = 3_700_000  # API 한도 5MB는 base64 기준이라 원본은 ~3.7MB 이하로

st.set_page_config(page_title="Logpresso 어시스턴트", page_icon="🔎", layout="centered")


def get_client() -> Anthropic:
    api_key = st.session_state.get("api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        st.error("사이드바에 Anthropic API 키를 입력하거나 ANTHROPIC_API_KEY 환경변수를 설정하세요.")
        st.stop()
    return Anthropic(api_key=api_key)


def prepare_image(data: bytes, media_type: str):
    """API 한도(긴 변 2576px, 5MB)에 맞게 줄입니다. 이미 맞으면 원본 그대로 보냄."""
    img = Image.open(io.BytesIO(data))
    if max(img.size) <= MAX_IMAGE_EDGE and len(data) <= MAX_IMAGE_BYTES:
        return data, media_type
    img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
    buf = io.BytesIO()
    # 스크린샷 글자 선명도 위해 PNG 우선, 그래도 크면 JPEG
    img.save(buf, "PNG", optimize=True)
    if buf.tell() <= MAX_IMAGE_BYTES:
        return buf.getvalue(), "image/png"
    for quality in (90, 75, 60, 40):
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=quality)
        if buf.tell() <= MAX_IMAGE_BYTES:
            return buf.getvalue(), "image/jpeg"
    raise ValueError("이미지 용량이 너무 커서 줄일 수 없습니다")


def call_claude(client: Anthropic, system, messages, effort=EFFORT, max_tokens=16000) -> str:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        output_config={"effort": effort},
        betas=[FALLBACK_BETA],
        fallbacks=FALLBACKS,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("모델이 이 요청에 대한 답변을 거부했습니다. 질문 표현을 바꿔 다시 시도해 주세요.")
    text = "".join(b.text for b in response.content if b.type == "text")
    if response.stop_reason == "max_tokens":
        text += "\n\n(답변이 길어 중간에 잘렸습니다.)"
    return text


TRANSCRIBE_PROMPT = (
    "첨부 이미지(로그프레소 화면 스크린샷 등)에 보이는 텍스트를 그대로 옮겨 적어라. "
    "에러 메시지, 쿼리문, 테이블명, 필드명, 명령어를 우선하고 철자/기호를 바꾸지 마라. "
    "읽을 수 없는 부분은 [판독불가]로 표시하고, 설명이나 해석은 붙이지 마라."
)


def transcribe_images(client: Anthropic, image_blocks) -> str:
    """검색(RAG)은 텍스트로만 되므로, 이미지 속 에러/쿼리 문구를 먼저 뽑아 검색어로 씁니다."""
    return call_claude(
        client,
        system=TRANSCRIBE_PROMPT,
        messages=[{"role": "user", "content": image_blocks + [{"type": "text", "text": "텍스트를 옮겨 적어줘."}]}],
        effort="low",
        max_tokens=4000,
    )


def parse_response(text: str, mode: str):
    if mode == "generate":
        query = re.search(r"<query>(.*?)</query>", text, re.DOTALL)
        explanation = re.search(r"<explanation>(.*?)</explanation>", text, re.DOTALL)
        clarification = re.search(r"<clarification>(.*?)</clarification>", text, re.DOTALL)
        return {
            "query": query.group(1).strip() if query else None,
            "explanation": explanation.group(1).strip() if explanation else None,
            "clarification": clarification.group(1).strip() if clarification else None,
        }
    else:
        diagnosis = re.search(r"<diagnosis>(.*?)</diagnosis>", text, re.DOTALL)
        solution = re.search(r"<solution>(.*?)</solution>", text, re.DOTALL)
        return {
            "diagnosis": diagnosis.group(1).strip() if diagnosis else None,
            "solution": solution.group(1).strip() if solution else None,
        }


# --- 사이드바 ---
with st.sidebar:
    st.header("설정")
    st.session_state["api_key"] = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.session_state.get("api_key", ""),
        help="비워두면 환경변수 ANTHROPIC_API_KEY를 사용합니다.",
    )
    mode_label = st.radio("모드", ["쿼리 생성", "에러/증상 진단"], index=0)
    mode = "generate" if mode_label == "쿼리 생성" else "diagnose"

    show_sources = st.checkbox("참고한 출처 표시", value=True)

    if st.button("대화 초기화"):
        st.session_state.pop("history", None)
        st.rerun()

    st.caption("지식베이스를 업데이트했다면 chunk_documents.py -> build_index.py를 다시 실행하세요.")

# --- 메인 ---
st.title("🔎 Logpresso 어시스턴스")
st.caption("자연어 쿼리 생성 + 에러/증상 진단. 사내 매뉴얼과 과거 사례를 검색해서 답변합니다.")

tab_chat, tab_history = st.tabs(["채팅", "기록"])

with tab_chat:
    if "history" not in st.session_state:
        st.session_state["history"] = []

    for msg in st.session_state["history"]:
        with st.chat_message(msg["role"]):
            for img in msg.get("images", []):
                st.image(img)
            st.markdown(msg["display"])

    placeholder = (
        "예: 최근 1시간 동안 차단된 방화벽 로그를 IP별로 집계해줘"
        if mode == "generate"
        else "예: table firewall_log 쿼리가 'unknown field' 에러를 내는데 원인이 뭘까?"
    )
    submitted = st.chat_input(
        placeholder + " (스크린샷 첨부/붙여넣기 가능)",
        accept_file="multiple",
        file_type=["png", "jpg", "jpeg", "gif", "webp"],
    )

    if submitted:
        user_input = submitted.text or ""
        files = submitted.files
        images, content = [], []
        for f in files:
            try:
                data, media_type = prepare_image(f.getvalue(), "image/jpeg" if f.type == "image/jpg" else f.type)
            except Exception as e:
                st.error(f"이미지를 열 수 없습니다 ({f.name}): {e}")
                st.stop()
            images.append(data)
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": base64.b64encode(data).decode()},
                }
            )
        content.append({"type": "text", "text": user_input or "첨부한 이미지를 분석해줘."})

        st.session_state["history"].append(
            {"role": "user", "content": content, "display": user_input, "images": images}
        )
        with st.chat_message("user"):
            for img in images:
                st.image(img)
            st.markdown(user_input)

        client = get_client()
        try:
            transcript = ""
            if images:
                with st.spinner("이미지 판독 중..."):
                    transcript = transcribe_images(client, content[:-1])
            search_text = f"{user_input}\n{transcript}".strip()
            log_question = user_input + (f"\n[이미지 {len(images)}장 판독]\n{transcript}" if images else "")
            st.session_state["history"][-1]["search_text"] = search_text
            # 후속 질문("버전은 4.0이야")만으로는 검색이 빗나가므로 직전 질문 내용도 함께 검색
            prev = next(
                (m.get("search_text", "") for m in reversed(st.session_state["history"][:-1]) if m["role"] == "user"),
                "",
            )
            query_text = f"{prev}\n{search_text}".strip()

            with st.spinner("관련 자료 검색 중..."):
                hits = retrieve(query_text, top_k=TOP_K)
                context = format_context(hits)
                if mode == "diagnose":
                    found = lookup(query_text)
                    if found:
                        context = format_sections(found) + "\n\n---\n\n" + context
                        hits = [
                            {"source": f"공식 매뉴얼: {name} 명령어 (직접 조회)", "score": 1.0} for name, _ in found
                        ] + hits

            api_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["history"]
                if m["role"] in ("user", "assistant")
            ]
            with st.spinner("답변 생성 중..."):
                raw_text = call_claude(client, build_system_prompt(mode, context), api_messages)
        except (anthropic.APIError, RuntimeError) as e:
            # 실패한 질문을 기록에서 빼야 다음 질문 때 답 없는 user 메시지가 쌓이지 않음
            st.session_state["history"].pop()
            msg = "API 키가 올바르지 않습니다." if isinstance(e, anthropic.AuthenticationError) else str(e)
            st.error(f"요청 실패: {msg}")
            st.stop()

        with st.chat_message("assistant"):
            parsed = parse_response(raw_text, mode)

            if mode == "generate":
                if parsed["clarification"]:
                    display = f"**추가 정보가 필요합니다:**\n\n{parsed['clarification']}"
                elif parsed["query"]:
                    display = f"```\n{parsed['query']}\n```\n\n{parsed['explanation'] or ''}"
                else:
                    display = raw_text
            else:
                if parsed["diagnosis"] or parsed["solution"]:
                    display = f"**진단**\n\n{parsed['diagnosis'] or '(불확실)'}\n\n**해결 방법**\n\n{parsed['solution'] or ''}"
                else:
                    display = raw_text

            st.markdown(display)

            if show_sources and hits:
                with st.expander(f"참고한 출처 {len(hits)}개"):
                    for h in hits:
                        st.markdown(f"- `{h['source']}` (유사도 {h['score']:.2f})")

        st.session_state["history"].append({"role": "assistant", "content": raw_text, "display": display})
        log_interaction(mode=mode, question=log_question, answer=display, sources=hits)

with tab_history:
    st.subheader("질문 기록")
    st.caption("로컬 파일(data/query_log.jsonl)에 저장된 과거 질문/답변입니다. 정확도가 낮았던 사례를 찾아 지식베이스 보강에 활용하세요.")

    records = load_history()
    if not records:
        st.info("아직 기록이 없습니다.")
    else:
        mode_filter = st.selectbox("모드 필터", ["전체", "쿼리 생성", "에러/증상 진단"])
        keyword = st.text_input("질문 검색 (키워드)")

        filtered = records
        if mode_filter != "전체":
            target = "generate" if mode_filter == "쿼리 생성" else "diagnose"
            filtered = [r for r in filtered if r["mode"] == target]
        if keyword:
            filtered = [r for r in filtered if keyword.lower() in r["question"].lower()]

        st.caption(f"{len(filtered)}건")
        for r in filtered:
            label = "생성" if r["mode"] == "generate" else "진단"
            with st.expander(f"[{r['timestamp']}] ({label}) {r['question'][:50]}"):
                st.markdown(f"**질문**\n\n{r['question']}")
                st.markdown(f"**답변**\n\n{r['answer']}")
                if r["sources"]:
                    src_lines = "\n".join(f"- `{s['source']}` (유사도 {s['score']})" for s in r["sources"])
                    st.markdown(f"**참고 출처**\n\n{src_lines}")