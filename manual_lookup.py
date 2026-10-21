"""
공식 쿼리 매뉴얼에서 명령어별 섹션(문법/옵션/오류 코드 표)을 직접 찾아옵니다.

의미 검색(retriever.py)은 매뉴얼을 1500자 단위로 잘라 검색하기 때문에, 사용자 쿼리에 쓰인
명령어의 "문법 + 오류 코드" 부분이 통째로 잡힌다는 보장이 없습니다. 진단 정확도를 위해
사용자 텍스트에 등장한 명령어/오류 코드/오류 메시지로 해당 섹션을 정확히 찾아 붙입니다.
"""

import json
import re
from functools import lru_cache

KB_PATH = "data/knowledge_base.jsonl"
MAX_SECTION_CHARS = 6000
MAX_SECTIONS = 5

# 매뉴얼의 명령어 섹션 시작: "\n\n<명령어>\n\n<한 줄 설명>\n\n명령어 속성\n"
_SECTION_RE = re.compile(r"\n\n([a-z][a-z0-9\-_.]*)\n\n[^\n]+\n\n명령어 속성\n")
_CMD_RE = re.compile(r"(?:^|\|)\s*([a-z][a-z0-9\-_.]*)", re.MULTILINE)
_CODE_RE = re.compile(r"(?<!\d)\d{5}(?!\d)")
_ERROR_ROW_RE = re.compile(r"^\| (\d{5}) \| ([^|]+) \|", re.MULTILINE)


@lru_cache(maxsize=1)
def _sections():
    """{명령어: 섹션 텍스트(사용 예 제외)}"""
    manual = ""
    with open(KB_PATH, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("folder", "").startswith("official_manual"):
                manual = r["content"]
                break
    matches = list(_SECTION_RE.finditer(manual))
    sections = {}
    for m, nxt in zip(matches, matches[1:] + [None]):
        body = manual[m.start() : nxt.start() if nxt else len(manual)].strip()
        # 사용 예는 길고 진단에 덜 중요해서 제외 (문법/옵션/오류 코드/설명만)
        body = body.split("\n\n사용 예\n\n")[0]
        sections.setdefault(m.group(1), body[:MAX_SECTION_CHARS])
    return sections


@lru_cache(maxsize=1)
def _error_index():
    """오류 코드/메시지 -> [명령어]. 같은 코드·메시지를 여러 명령어가 공유함(예: stats와 cube).
    메시지는 {변수}를 뺀 가장 긴 고정 부분만 사용."""
    by_code, by_msg = {}, {}
    for name, body in _sections().items():
        for code, msg in _ERROR_ROW_RE.findall(body):
            by_code.setdefault(code, []).append(name)
            fixed = max(re.split(r"\{[^}]*\}", msg.strip()), key=len).strip(" .")
            if len(fixed) >= 8:  # "잘못된 쿼리 입니다" 같은 흔한 짧은 문구는 오탐이 많아 제외
                by_msg.setdefault(fixed, []).append(name)
    return by_code, by_msg


def lookup(text: str):
    """text에 등장한 오류 코드/메시지/명령어에 해당하는 매뉴얼 섹션 [(명령어, 섹션)]."""
    sections = _sections()
    by_code, by_msg = _error_index()
    used = [c for c in _CMD_RE.findall(text) if c in sections]
    hits = [by_code.get(c, []) for c in _CODE_RE.findall(text)]
    hits += [owners for msg, owners in by_msg.items() if msg in text]
    names = []
    for owners in hits:
        # 공유 코드면 사용자 쿼리에 실제로 쓰인 명령어만, 쿼리가 없으면 후보 몇 개
        names += [n for n in owners if n in used] or owners[:3]
    names += used
    seen = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return [(n, sections[n]) for n in seen[:MAX_SECTIONS]]


def format_sections(found) -> str:
    return "\n\n---\n\n".join(f"[공식 매뉴얼: {name} 명령어]\n{body}" for name, body in found)


if __name__ == "__main__":
    s = _sections()
    assert "stats" in s and "21702" in s["stats"], "매뉴얼 파싱 실패"
    got = [n for n, _ in lookup("table duration=1d x | stats foo(a) by b\n21702 에러")]
    assert got[0] == "stats" and "table" in got and "cube" not in got, got
    assert "stats" in [n for n, _ in lookup("집계 함수를 입력하세요.")]
    assert lookup("평범한 문장 12345") == []
    print(f"ok: 명령어 섹션 {len(s)}개, 오류 코드 {len(_error_index()[0])}개")
