"""
chunks.jsonl을 임베딩해서 로컬 ChromaDB 벡터 인덱스를 만듭니다.
임베딩은 로컬 다국어 모델(sentence-transformers)을 사용하므로 API 비용이 들지 않습니다.

사용법:
    pip install -r requirements.txt
    python build_index.py          # 증분: 새로 생기거나 바뀐 청크만 임베딩, 사라진 청크는 삭제
    python build_index.py --full   # 인덱스를 지우고 전체를 처음부터 다시 임베딩

청크 ID가 내용 해시(chunk_documents.py)라서, 문서를 추가해도 기존 문서는 다시 임베딩하지 않습니다.
임베딩 모델(EMBED_MODEL_NAME)을 바꾸면 기존 벡터와 섞일 수 없으므로 자동으로 전체 재구축합니다.
"""

import json
import shutil
import os
import sys

import chromadb
from sentence_transformers import SentenceTransformer

CHUNKS_PATH = "data/chunks.jsonl"
INDEX_DIR = "data/chroma_db"
COLLECTION_NAME = "logpresso_kb"

# 다국어(한국어 포함) 성능이 좋은 경량 모델. GPU 있으면 -large로 교체 가능.
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
BATCH_SIZE = 64
STEP = 500  # Chroma는 한 번에 너무 많은 항목을 넣으면 에러가 날 수 있어 배치로 추가/삭제


def open_collection(full: bool):
    """기존 컬렉션을 열되, --full이거나 다른 임베딩 모델로 만든 인덱스면 지우고 새로 만듭니다."""
    if not full and os.path.exists(INDEX_DIR):
        client = chromadb.PersistentClient(path=INDEX_DIR)
        try:
            collection = client.get_collection(COLLECTION_NAME)
        except Exception:
            collection = None
        if collection is not None and (collection.metadata or {}).get("embed_model") == EMBED_MODEL_NAME:
            return collection
        print("기존 인덱스가 없거나 다른 임베딩 모델로 만들어져 전체를 다시 구축합니다.")
        del client
    if os.path.exists(INDEX_DIR):
        shutil.rmtree(INDEX_DIR)
    client = chromadb.PersistentClient(path=INDEX_DIR)
    return client.create_collection(COLLECTION_NAME, metadata={"embed_model": EMBED_MODEL_NAME})


def main():
    full = "--full" in sys.argv
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f if line.strip()]
    collection = open_collection(full)

    existing = set(collection.get(include=[])["ids"])
    wanted = {c["chunk_id"] for c in chunks}
    to_delete = sorted(existing - wanted)
    to_add = [c for c in chunks if c["chunk_id"] not in existing]
    print(f"청크 {len(chunks)}개 중 새로 임베딩 {len(to_add)}개, 삭제 {len(to_delete)}개, 유지 {len(existing & wanted)}개")

    for i in range(0, len(to_delete), STEP):
        collection.delete(ids=to_delete[i : i + STEP])

    if to_add:
        print("임베딩 모델 로딩 중...")
        model = SentenceTransformer(EMBED_MODEL_NAME)
        # e5 계열 모델은 "passage: " 접두어를 붙여야 성능이 제대로 나옴
        texts = [f"passage: {c['content']}" for c in to_add]
        print("임베딩 계산 중 (새 청크 양에 따라 몇 분 걸릴 수 있습니다)...")
        embeddings = model.encode(texts, batch_size=BATCH_SIZE, show_progress_bar=True, normalize_embeddings=True)

        for i in range(0, len(to_add), STEP):
            batch = to_add[i : i + STEP]
            collection.add(
                ids=[c["chunk_id"] for c in batch],
                embeddings=embeddings[i : i + STEP].tolist(),
                documents=[c["content"] for c in batch],
                metadatas=[{"source": c["source"], "folder": c["folder"]} for c in batch],
            )

    print(f"인덱스 구축 완료: {INDEX_DIR} (컬렉션: {COLLECTION_NAME}, {collection.count()}개 청크)")


if __name__ == "__main__":
    main()
