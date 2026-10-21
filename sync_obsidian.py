"""
Obsidian vault(마크다운 노트 폴더)를 읽어서 data/obsidian_kb.jsonl로 변환합니다.
기존 knowledge_base.jsonl은 건드리지 않고 별도 파일로 추가되므로 안전합니다.

사용법:
    1. 아래 VAULT_PATH를 본인 Obsidian vault 경로로 수정
       (Obsidian 앱에서 좌측 vault 이름 우클릭 -> "폴더에서 보기"로 실제 경로 확인 가능)
    2. python sync_obsidian.py
    3. python chunk_documents.py    (obsidian_kb.jsonl도 함께 청킹됨)
    4. python build_index.py       (재색인)

노트를 추가/수정할 때마다 1~4를 반복하면 됩니다 (보통 1은 한 번만 설정).
"""

import json
import os
import re

# ---------------------------------------------------------------------------
# 본인 Obsidian vault 경로로 수정하세요.
# 윈도우 예시: r"C:\Users\<사용자>\Documents\MyVault"
# ---------------------------------------------------------------------------
VAULT_PATH = r"C:\path\to\your\obsidian-vault"

OUT_PATH = "data/obsidian_kb.jsonl"

# Obsidian 내부 설정 폴더 등은 지식베이스에서 제외
SKIP_DIRS = {".obsidian", ".trash", ".git"}

FRONTMATTER_RE = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(\|([^\]]+))?\]\]")  # [[문서]] 또는 [[문서|표시텍스트]]
PHONE_RE = re.compile(r"01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def clean_markdown(text: str) -> str:
    # YAML 프론트매터 제거
    text = FRONTMATTER_RE.sub("", text)
    # [[문서|표시텍스트]] -> 표시텍스트, [[문서]] -> 문서 (링크 문법만 제거하고 텍스트는 유지)
    text = WIKILINK_RE.sub(lambda m: m.group(3) or m.group(1), text)
    return text.strip()


def redact_pii(text: str) -> str:
    text = PHONE_RE.sub("[REDACTED-PHONE]", text)
    text = EMAIL_RE.sub("[REDACTED-EMAIL]", text)
    return text


def main():
    if not os.path.isdir(VAULT_PATH):
        print(f"vault 경로를 찾을 수 없습니다: {VAULT_PATH}")
        print("이 파일 상단의 VAULT_PATH를 본인 Obsidian vault 실제 경로로 수정하세요.")
        return

    records = []
    for root, dirs, files in os.walk(VAULT_PATH):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if not f.lower().endswith(".md"):
                continue
            path = os.path.join(root, f)
            rel = os.path.relpath(path, VAULT_PATH)

            with open(path, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()

            content = clean_markdown(raw)
            if not content:
                continue
            content = redact_pii(content)

            records.append(
                {
                    "source": f"obsidian:{rel}",
                    "folder": os.path.dirname(rel) or "obsidian_root",
                    "content": content,
                    "n_chars": len(content),
                    "redacted": False,
                }
            )

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        for r in records:
            out.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Obsidian 노트 {len(records)}개를 {OUT_PATH}로 변환했습니다.")
    print("다음 순서로 재색인하세요: python chunk_documents.py -> python build_index.py")


if __name__ == "__main__":
    main()
