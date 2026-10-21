"""
data/docs/ 폴더에 넣은 PDF/텍스트/마크다운 파일을 data/docs_kb.jsonl로 변환합니다.
기존 knowledge_base.jsonl은 건드리지 않고 별도 파일로 추가되므로 안전합니다.

사용법 (또는 학습.bat 더블클릭):
    1. data/docs/ 폴더에 .pdf / .txt / .md 파일을 넣기 (하위 폴더 가능)
    2. python sync_docs.py
    3. python chunk_documents.py
    4. python build_index.py
"""

import json
import os

from pypdf import PdfReader

from sync_obsidian import redact_pii

DOCS_DIR = "data/docs"
OUT_PATH = "data/docs_kb.jsonl"
KB_PATH = "data/knowledge_base.jsonl"
TEXT_EXTS = {".txt", ".md"}
# 원시 로그 덤프(수백만 자)는 검색 품질을 떨어뜨리고 색인만 느려짐. 가이드/노트는 보통 수만 자 이하
MAX_CHARS = 1_000_000


def existing_kb_names():
    """knowledge_base.jsonl에 이미 있는 파일명. 그쪽은 개인정보 마스킹된 버전이라 원본을 다시 넣지 않음."""
    if not os.path.exists(KB_PATH):
        return set()
    with open(KB_PATH, encoding="utf-8") as f:
        return {os.path.basename(json.loads(line)["source"]) for line in f if line.strip()}


def read_pdf(path: str) -> str:
    # 페이지 사이를 빈 줄로 나눠야 chunk_documents.py가 문단 경계로 자름
    return "\n\n".join((page.extract_text() or "").strip() for page in PdfReader(path).pages)


def read_text(path: str) -> str:
    for enc in ("utf-8-sig", "cp949"):  # 윈도우 메모장 기본 저장(ANSI)이 cp949
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main():
    os.makedirs(DOCS_DIR, exist_ok=True)
    kb_names = existing_kb_names()
    records, skipped, duplicates = [], [], 0
    for root, _, files in os.walk(DOCS_DIR):
        for name in files:
            ext = os.path.splitext(name)[1].lower()
            if ext != ".pdf" and ext not in TEXT_EXTS:
                continue
            if name in kb_names:
                duplicates += 1
                continue
            path = os.path.join(root, name)
            rel = os.path.relpath(path, DOCS_DIR)
            try:
                content = read_pdf(path) if ext == ".pdf" else read_text(path)
            except Exception as e:
                skipped.append(f"{rel} ({e})")
                continue
            content = redact_pii(content.strip())
            if not content:
                reason = "스캔본 PDF일 수 있음" if ext == ".pdf" else "빈 파일"
                skipped.append(f"{rel} (추출된 텍스트 없음 - {reason})")
                continue
            if len(content) > MAX_CHARS:
                skipped.append(f"{rel} ({len(content):,}자 - 원시 로그 등 너무 큰 파일)")
                continue
            records.append(
                {
                    "source": f"docs:{rel}",
                    "folder": os.path.dirname(rel) or "docs_root",
                    "content": content,
                    "n_chars": len(content),
                    "redacted": False,
                }
            )

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        for r in records:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"{DOCS_DIR} 문서 {len(records)}개를 {OUT_PATH}로 변환했습니다.")
    if duplicates:
        print(f"  knowledge_base.jsonl에 같은 파일명이 이미 있어 건너뜀: {duplicates}개 (마스킹된 기존 버전 사용)")
    for s in skipped:
        print(f"  건너뜀: {s}")


if __name__ == "__main__":
    main()
