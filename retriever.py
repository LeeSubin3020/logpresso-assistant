"""
로컬 ChromaDB 인덱스에서 질문과 관련된 지식베이스 청크를 검색합니다.

v0.5 변경점:
- 의미 검색(semantic) 후보를 넉넉히 뽑은 다음, 질문 키워드가 실제로 등장하는지로
  재정렬(하이브리드 검색)해서 "의미는 비슷한데 엉뚱한 문서"가 상위에 오는 걸 줄임.
- 임베딩 모델을 e5-large로 교체 가능 (EMBED_MODEL_NAME 참고).
"""

import re

import chromadb
from sentence_transformers import SentenceTransformer

INDEX_DIR = "data/chroma_db"
COLLECTION_NAME = "logpresso_kb"

# 정확도를 더 올리고 싶으면 아래를 "intfloat/multilingual-e5-large"로 교체 후
# build_index.py를 재실행하세요. (모델 용량 ~2GB, base 대비 정확도 향상, 속도/메모리 부담 증가)
EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"

# 의미 검색에서 몇 배수로 후보를 넉넉히 뽑아 키워드 재정렬할지
CANDIDATE_MULTIPLIER = 4

_model = None
_collection = None

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_.]+|[가-힣]+")
_STOPWORDS = {"어떻게", "무엇", "뭐야", "알려줘", "해줘", "하는", "이거", "저거", "그거", "쿼리", "로그프레소"}


def _get_model():
    global _model
    if _model is None:
        try:
            # 캐시된 모델은 오프라인으로 로드해 매번 "업데이트 확인" 네트워크를 타지 않게 함
            # (인터넷이 끊겼을 때 getaddrinfo failed로 멈추는 것 방지)
            _model = SentenceTransformer(EMBED_MODEL_NAME, local_files_only=True)
        except Exception:
            # 다른 PC로 옮긴 직후처럼 캐시가 없으면 이번 한 번만 온라인으로 받음
            try:
                _model = SentenceTransformer(EMBED_MODEL_NAME)
            except Exception as e:
                raise RuntimeError(
                    "임베딩 모델을 로드하지 못했습니다. 이 PC에 모델 캐시가 없어 처음 한 번은 "
                    f"인터넷 연결이 필요합니다. (원본 에러: {e})"
                ) from e
    return _model


def _get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=INDEX_DIR)
        _collection = client.get_collection(COLLECTION_NAME)
    return _collection


def _extract_keywords(query: str):
    tokens = _TOKEN_RE.findall(query.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


def _keyword_score(content: str, keywords: list) -> float:
    """content에 등장하는 키워드 비율 (0~1). 명령어/필드명처럼 정확히 일치해야 하는
    토큰이 실제로 문서에 존재하는지를 잡아내기 위한 용도."""
    if not keywords:
        return 0.0
    content_lower = content.lower()
    hit = sum(1 for k in keywords if k in content_lower)
    return hit / len(keywords)


def retrieve(query: str, top_k: int = 8):
    """질문과 가장 관련 있는 청크 top_k개를 하이브리드(의미+키워드) 검색으로 반환합니다.

    반환: [{"content": str, "source": str, "folder": str, "score": float}, ...]
    """
    model = _get_model()
    collection = _get_collection()
    keywords = _extract_keywords(query)

    # e5 계열 모델은 질의문에 "query: " 접두어 필요
    query_embedding = model.encode([f"query: {query}"], normalize_embeddings=True)[0].tolist()

    n_candidates = min(top_k * CANDIDATE_MULTIPLIER, 60)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
    )

    candidates = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    if not docs:
        return []

    max_dist = max(dists) or 1.0
    for doc, meta, dist in zip(docs, metas, dists):
        semantic_score = 1 - (dist / max_dist)  # 후보군 내 상대 정규화 (0~1)
        kw_score = _keyword_score(doc, keywords)
        final_score = 0.65 * semantic_score + 0.35 * kw_score
        candidates.append(
            {
                "content": doc,
                "source": meta.get("source", ""),
                "folder": meta.get("folder", ""),
                "score": final_score,
            }
        )

    candidates.sort(key=lambda h: h["score"], reverse=True)
    return candidates[:top_k]


def format_context(hits, max_chars: int = 9000) -> str:
    """검색 결과를 시스템 프롬프트에 넣을 텍스트로 포맷팅합니다."""
    parts = []
    used = 0
    for h in hits:
        block = f"[출처: {h['source']}]\n{h['content']}"
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n\n---\n\n".join(parts)