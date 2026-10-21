"""
data/ 폴더 안의 모든 *.jsonl 지식베이스 파일(knowledge_base.jsonl, obsidian_kb.jsonl 등)을
RAG용 청크로 분할합니다.

사용법:
    python chunk_documents.py

입력: data/*.jsonl (chunks.jsonl 자기 자신은 제외), 각 줄: {"source", "folder", "content", ...}
출력: data/chunks.jsonl (각 줄: {"chunk_id", "source", "folder", "content"}, chunk_id는 내용 해시)
"""

import glob
import hashlib
import json
import os

MAX_CHARS = 1500
OVERLAP_CHARS = 200

DATA_DIR = "data"
OUT_PATH = "data/chunks.jsonl"


def split_into_chunks(text: str, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS):
    """문단(빈 줄) 경계를 우선 존중하면서 max_chars 단위로 청크를 나눕니다."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        return [text.strip()] if text.strip() else []

    chunks = []
    current = ""

    for para in paragraphs:
        # 문단 자체가 max_chars보다 크면 강제로 자름
        if len(para) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for i in range(0, len(para), max_chars - overlap):
                chunks.append(para[i : i + max_chars])
            continue

        if len(current) + len(para) + 2 <= max_chars:
            current = f"{current}\n\n{para}" if current else para
        else:
            if current:
                chunks.append(current)
            # 오버랩: 이전 청크 끝부분 일부를 새 청크 시작에 포함
            tail = current[-overlap:] if current else ""
            current = f"{tail}\n\n{para}" if tail else para

    if current:
        chunks.append(current)

    return chunks


def find_source_files():
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*.jsonl")))
    # chunks.jsonl(출력 파일)과 query_log.jsonl(질문 기록, logger.py)은 지식베이스가 아니므로 제외
    return [p for p in paths if os.path.basename(p) not in ("chunks.jsonl", "query_log.jsonl")]


def main():
    source_files = find_source_files()
    if not source_files:
        print(f"경고: {DATA_DIR} 폴더에 지식베이스 jsonl 파일이 없습니다.")
        return

    records = []
    for path in source_files:
        with open(path, encoding="utf-8") as f:
            file_records = [json.loads(line) for line in f if line.strip()]
        print(f"  {path}: {len(file_records)}개 문서")
        records.extend(file_records)

    all_chunks = {}

    for r in records:
        pieces = split_into_chunks(r["content"])
        for p in pieces:
            # 내용 기반 ID: 문서가 안 바뀌면 ID도 그대로라 build_index.py가 새/바뀐 청크만 임베딩함
            cid = hashlib.sha1(f"{r['source']}\0{p}".encode("utf-8")).hexdigest()[:20]
            all_chunks[cid] = {"chunk_id": cid, "source": r["source"], "folder": r.get("folder", ""), "content": p}
    all_chunks = list(all_chunks.values())

    with open(OUT_PATH, "w", encoding="utf-8") as out:
        for c in all_chunks:
            out.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"\n입력 파일 {len(source_files)}개, 문서 {len(records)}개 -> 청크: {len(all_chunks)}개")
    print(f"저장 완료: {OUT_PATH}")


if __name__ == "__main__":
    main()
