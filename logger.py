"""
질문/답변 기록을 로컬 파일에 저장하고 불러옵니다.
정확도 튜닝 시 "어떤 질문에서 검색이 빗나갔는지" 되짚어보는 용도로 사용하세요.
"""

import json
import os
from datetime import datetime

LOG_PATH = "data/query_log.jsonl"


def log_interaction(mode: str, question: str, answer: str, sources: list):
    """한 번의 질문-답변을 로그 파일에 한 줄(JSON) 추가."""
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "question": question,
        "answer": answer,
        "sources": [{"source": s["source"], "score": round(s["score"], 3)} for s in sources],
    }
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_history(limit: int = 200):
    """최근 기록을 최신순으로 반환."""
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        lines = [json.loads(l) for l in f if l.strip()]
    return list(reversed(lines))[:limit]
