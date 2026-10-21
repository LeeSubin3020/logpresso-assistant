"""질문 목록을 에이전트(RAG)와 같은 모델(RAG 없음)에 물어 answers/ 에 답변을 저장한다.

  answers/agent_v1.md : 개선 전 에이전트 프롬프트 (eval/prompts_v1.py, 개선 직전 prompts.py 복사본)
  answers/agent_v2.md : 현재 prompts.py 의 에이전트 (검색 근거 + 환각 방지 프롬프트)
  answers/llm_only.md : 같은 모델에 질문만 전달 (RAG 효과를 분리해서 보기 위한 비교군)

  py collect_agent.py --version v2            # 에이전트 v2, 질문 전체
  py collect_agent.py --version v1 --from 17  # 에이전트 v1, Q17 이후만 (이미 받은 문항은 그대로 둠)
  py collect_agent.py --baseline --from 17    # RAG 없는 비교군

ANTHROPIC_API_KEY 필요. 질문당 API를 1번 호출하므로 비용이 든다. 인덱스가 먼저 만들어져 있어야 한다 (학습.bat).
이미 있는 답변 파일에는 요청한 문항만 덮어쓴다.
GPT·Gemini 는 API 대신 질문을 직접 붙여넣고 답변을 answers/gpt.md, answers/gemini.md 로 저장한다.
"""
import argparse
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)  # retriever.py 가 data/chroma_db 를 상대 경로로 읽는다
sys.path[:0] = [ROOT, HERE]

from anthropic import Anthropic

from evaluate import load_answers, load_questions
from manual_lookup import format_sections, lookup
from retriever import format_context, retrieve

# app.py 와 같은 설정 (app.py 는 Streamlit 앱이라 import 할 수 없어 값을 복사)
MODEL = "claude-opus-5-5"
EFFORT = "high"
TOP_K = 8
FALLBACKS = [{"model": "claude-opus-4-8"}]
FALLBACK_BETA = "server-side-fallback-2026-06-01"
PLAIN = "당신은 로그프레소(Logpresso) 쿼리 작성 도우미입니다. 질문에 맞는 로그프레소 쿼리를 작성하세요."


def ask(client, system, question):
    try:
        r = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=system, messages=[{"role": "user", "content": question}],
            output_config={"effort": EFFORT}, betas=[FALLBACK_BETA], fallbacks=FALLBACKS)
        return "".join(b.text for b in r.content if b.type == "text")
    except Exception as e:  # 한 문항이 실패해도 나머지는 계속 (채점에서 '쿼리 없음'으로 보인다)
        return f"(API 오류: {e})"


def rag_system(build_system_prompt, question, category):
    mode = "diagnose" if category == "진단" else "generate"  # app.py 와 같은 흐름
    context = format_context(retrieve(question, top_k=TOP_K))
    if mode == "diagnose":
        found = lookup(question)
        if found:
            context = format_sections(found) + "\n\n---\n\n" + context
    return build_system_prompt(mode, context)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", choices=["v1", "v2"], default="v2", help="에이전트 프롬프트 버전 (기본 v2 = 현재 prompts.py)")
    ap.add_argument("--baseline", action="store_true", help="에이전트 대신 RAG 없는 같은 모델(llm_only)을 수집")
    ap.add_argument("--from", dest="first", type=int, default=1, help="이 번호 이후의 문항만 수집 (예: 17)")
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("환경변수 ANTHROPIC_API_KEY 가 필요합니다.")
    client = Anthropic()
    if args.baseline:
        name, make_system = "llm_only", lambda q, c: PLAIN
    else:
        build = importlib.import_module("prompts_v1" if args.version == "v1" else "prompts").build_system_prompt
        name, make_system = f"agent_{args.version}", lambda q, c: rag_system(build, q, c)

    out = os.path.join(HERE, "answers")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}.md")
    answers = load_answers(out).get(name, {}) if os.path.exists(path) else {}
    for q in load_questions():
        if int(q["id"][1:]) < args.first:
            continue
        print(f"{name} {q['id']}", flush=True)
        answers[q["id"]] = ask(client, make_system(q["question"], q["category"]), q["question"])
        with open(path, "w", encoding="utf-8") as f:  # 문항마다 저장해 중간에 멈춰도 받은 답은 남긴다
            f.write("\n".join(f"### {i}\n\n{answers[i]}\n" for i in sorted(answers)))
    print("완료. python evaluate.py run 으로 채점하세요.")


if __name__ == "__main__":
    main()
