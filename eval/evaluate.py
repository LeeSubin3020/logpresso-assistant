"""LLM이 만든 로그프레소 쿼리를 테스트 서버에서 실제로 실행해 채점한다.

채점 기준 (질문마다 정답 쿼리 gold_query가 있고, 같은 샘플 데이터에 둘 다 실행해 비교)
  정답        : 실행 성공 + 결과 값이 정답 쿼리와 같음
  결과 다름   : 실행은 되지만 결과 값이 다름 (필드·조건·집계가 틀림)
  오류        : 서버가 거부 (없는 명령어, SQL/Splunk 문법, 옵션·정규식 오류, 없는 테이블 등)
  쿼리 없음   : 답변에서 쿼리를 찾지 못함
  차단        : 서버 데이터를 바꿀 수 있는 명령어라 실행하지 않음

사용법
  set LOGPRESSO_URL=https://<서버>  &  set LOGPRESSO_API_KEY=<API 키>
  python evaluate.py setup       # 샘플 테이블(eval_fw, eval_web)을 새로 만들고 데이터 입력
  python evaluate.py questions   # LLM에 붙여넣을 질문 목록 출력
  python evaluate.py run         # answers/*.md 를 채점해 results/ 에 표와 리포트 생성
"""
import argparse
import csv
import datetime as dt
import glob
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.environ.get("LOGPRESSO_URL", "https://localhost").rstrip("/") + "/api/sonar/"
KEY = os.environ.get("LOGPRESSO_API_KEY")
CTX = ssl._create_unverified_context()  # 사설 인증서 서버
# 서버 데이터를 바꾸거나 파일을 만드는 명령어는 실행하지 않는다
BLOCKED = re.compile(r"^(import|output\w*|create\w*|remove\w*|delete\w*|truncate\w*)$", re.I)


def api(method, path, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(BASE + path, data=body, method=method, headers={"Authorization": "Bearer " + (KEY or "")})
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def run_query(q, limit=1000):
    """(rows, error). 오류는 '(코드) 메시지' 문자열."""
    status, body = api("GET", "query?" + urllib.parse.urlencode({"q": q, "limit": limit}))
    if status == 200:
        return [json.loads(l) for l in body.splitlines() if l.strip()], None
    # 서버가 오류 메시지에 정규식·줄바꿈을 이스케이프 없이 넣는 경우가 있어 JSON 대신 정규식으로 꺼낸다
    m = re.search(r'"error_msg"\s*:\s*"(.*)"\s*}', body, re.S)
    return None, (m.group(1).splitlines()[0] if m else f"HTTP {status}: {body[:80]}")


# ---------- 샘플 데이터 ----------

def sample_rows(now):
    """최근 1시간 안에 1분 간격으로 쌓인 것처럼 만든 가상 로그. 모든 값은 가상이다."""
    ts = lambda i, n: (now - dt.timedelta(minutes=n - 1 - i)).strftime("%Y-%m-%d %H:%M:%S")
    fw = [{"_time": ts(i, 60), "src_ip": f"10.0.0.{i % 5 + 1}", "dst_ip": f"203.0.113.{i % 3 + 1}",
           "dst_port": [80, 443, 22, 3389, 8080][i % 5], "action": "deny" if i % 4 == 0 else "allow", "bytes": 100 * (i + 1)}
          for i in range(60)]
    web = []
    for i in range(40):
        status = 404 if i % 7 == 0 else 500 if i % 11 == 0 else 200
        uri = "/index.html" if i % 10 < 4 else "/login" if i % 10 < 7 else "/api/data" if i % 10 < 9 else "/admin"
        method = "POST" if i % 5 == 0 else "GET"
        stamp = (now - dt.timedelta(minutes=39 - i)).strftime("%d/%b/%Y:%H:%M:%S +0900")
        web.append({"_time": ts(i, 40), "line": f'198.51.100.{i % 8 + 1} - - [{stamp}] "{method} {uri} HTTP/1.1" {status} {100 + i}'})
    return {"eval_fw": fw, "eval_web": web}


def wait(table, exists, seconds=60):
    for _ in range(seconds):
        found = run_query(f"table {table} | stats count", 1)[1] is None
        if found == exists:
            return
        time.sleep(1)
    sys.exit(f"{table} 테이블이 {'생성' if exists else '삭제'}되지 않았습니다.")


def setup():
    if not KEY:
        sys.exit("환경변수 LOGPRESSO_URL, LOGPRESSO_API_KEY 를 먼저 설정하세요 (README 참고).")
    try:
        status, body = api("GET", "tables?limit=1")
    except OSError as e:
        sys.exit(f"서버에 접속할 수 없습니다 ({BASE}): {e}")
    if status != 200:
        sys.exit(f"서버가 요청을 거부했습니다: HTTP {status} {body[:200]} - API 키를 확인하세요.")
    for table, rows in sample_rows(dt.datetime.now()).items():
        # 삭제·생성이 비동기로 반영되므로, 삭제가 끝난 것을 확인한 뒤 만들어야 새 데이터가 같이 지워지지 않는다
        print(f"{table}: 기존 테이블 삭제 후 새로 만드는 중 (10~20초 걸립니다)", flush=True)
        api("DELETE", f"tables/{table}")
        wait(table, exists=False)
        status, body = api("POST", "tables", {"table": table})
        if status >= 300:
            sys.exit(f"{table} 테이블 생성 요청이 거부됐습니다: HTTP {status} {body[:200]}")
        wait(table, exists=True)
        for i in range(0, len(rows), 20):  # GET 주소 길이 제한 때문에 나눠서 입력
            lit = json.dumps(rows[i:i + 20], ensure_ascii=False).replace("\\", "\\\\").replace('"', '\\"')
            _, err = run_query(f'json "{lit}" | eval _time = date(_time, "yyyy-MM-dd HH:mm:ss") | import {table}', 1)
            if err:
                sys.exit(f"{table} 입력 실패: {err}")
        print(f"{table}: {run_query(f'table {table} | stats count')[0]}")


# ---------- 질문 / 답변 ----------

def load_questions():
    with open(os.path.join(HERE, "questions.csv"), encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_answers(folder):
    """answers/<시스템>.md 안의 'Q01' 제목 줄('### Q01', '**Q01**', 'Q01. 제목' 모두 허용) 아래 내용이 그 문항의 답변."""
    systems = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.md"))):
        text = open(path, encoding="utf-8-sig").read()
        parts = re.split(r"^[ \t]*(?:#{1,6}[ \t]*)?\**[ \t]*(Q\d+)\b[^\n]*$", text, flags=re.M)
        systems[os.path.splitext(os.path.basename(path))[0]] = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return systems


def extract_query(answer):
    """<query> 태그 → <solution> 안 코드블록 → 첫 코드블록 → 답변 전체가 한 줄 쿼리인 경우."""
    m = re.search(r"<query>(.*?)</query>", answer, re.S)
    if m:
        return m.group(1).strip()
    scope = (re.search(r"<solution>(.*?)</solution>", answer, re.S) or [None, answer])[1]
    # 문법 표기용 블록(`table [duration=기간] 테이블이름`처럼 대괄호 안에 한글 자리표시자)은 쿼리가 아니므로 건너뛴다
    # 오류 부분만 따로 보여 주는 조각(`"\"(?<method>[A-Z]+ "` 등)도 쿼리가 아니므로, table/system/json 으로 시작하는 블록을 우선한다
    blocks = [m.group(1).strip() for m in re.finditer(r"```[^\n`]*\n(.*?)```", scope, re.S)
              if not re.search(r"\[[a-z_]+=[^\]]*[가-힣]", m.group(1))]
    for b in blocks:
        if re.match(r"(table|system|json)\s", b, re.I):
            return b
    if blocks:
        return blocks[0]
    # 웹 화면에서 복사하면 코드블록 표시(```)가 사라지는 경우가 있어, table/system/json 으로 시작하는 줄과 그 뒤 '|' 줄을 쿼리로 본다
    lines = answer.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"\s*(table|system|json)\s", line, re.I):
            parts = [line.strip()]
            for nxt in lines[i + 1:]:
                if not nxt.strip().startswith("|"):
                    break
                parts.append(nxt.strip())
            return " ".join(parts)
    return ""


def normalize(rows):
    """필드 이름은 무시하고 값만 비교 (LLM마다 count/cnt 처럼 이름을 다르게 붙이므로)."""
    def val(v):
        return format(float(v), ".4f") if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)
    return sorted(tuple(sorted(val(v) for v in r.values())) for r in rows)


def grade(query, gold_rows):
    if not query:
        return "쿼리 없음", "답변에서 쿼리를 찾지 못함", 0
    if any(BLOCKED.match(seg.strip().split(" ")[0]) for seg in query.split("|")):
        return "차단", "데이터를 바꾸는 명령어 포함", 0
    rows, err = run_query(query)
    if err:
        return "오류", err, 0
    if normalize(rows) == normalize(gold_rows):
        return "정답", "", len(rows)
    return "결과 다름", f"결과 값이 다름 ({len(rows)}행, 정답 {len(gold_rows)}행)", len(rows)


# ---------- 리포트 ----------

CELL = {"정답": ("✓", "#1a7f37"), "결과 다름": ("△", "#9a6700"), "오류": ("✕", "#cf222e"), "쿼리 없음": ("✕", "#cf222e"), "차단": ("✕", "#cf222e")}


def short(reason):
    m = re.match(r"\(([\w-]+)\)\s*(.*)", reason)
    return (m.group(2).split(":")[0] if m else reason)[:22]


def write_report(questions, systems, grades, out_dir):
    names = list(systems)
    total = len(questions)
    stat = lambda s, kinds: sum(1 for q in questions if grades[(q["id"], s)][0] in kinds)
    head = "".join(f"<th>{html.escape(n)}</th>" for n in names)
    summary = "".join(
        f"<tr><td>{html.escape(label)}</td>" + "".join(f"<td><b>{stat(n, kinds)}</b> / {total} <span>({stat(n, kinds) * 100 // total}%)</span></td>" for n in names) + "</tr>"
        for label, kinds in (("실행 성공", ("정답", "결과 다름")), ("정답 (결과 일치)", ("정답",)), ("오류", ("오류", "쿼리 없음", "차단"))))
    rows = ""
    for q in questions:
        cells = ""
        for n in names:
            kind, reason, _ = grades[(q["id"], n)]
            mark, color = CELL[kind]
            note = f"<br><small>{html.escape(short(reason))}</small>" if kind in ("오류", "쿼리 없음", "차단") else ""
            cells += f'<td style="color:{color}"><b>{mark}</b> {kind}{note}</td>'
        rows += f"<tr><td>{q['id']}</td><td>{html.escape(q['category'])}</td><td class='q'>{html.escape(q['title'])}</td>{cells}</tr>"
    page = f"""<!doctype html><meta charset="utf-8"><title>쿼리 정확도 비교</title><style>
body{{font-family:'Malgun Gothic',sans-serif;margin:24px;color:#1f2328;background:#fff}}
h2{{margin:0 0 4px}} p{{color:#57606a;font-size:13px;margin:0 0 14px}}
table{{border-collapse:collapse;margin-bottom:22px;font-size:13px}}
th{{background:#f3f5f7;text-align:left;padding:7px 12px;border-bottom:2px solid #d0d7de}}
td{{padding:6px 12px;border-bottom:1px solid #eaeef2;vertical-align:top}} td span{{color:#57606a}}
td.q{{max-width:340px}} small{{color:#8c959f}}</style>
<h2>로그프레소 쿼리 정확도 비교</h2>
<p>같은 질문 {total}개를 각 시스템에 입력하고, 답변 쿼리를 테스트 서버의 샘플 데이터에 실행해 정답 쿼리 결과와 비교했습니다. ({dt.date.today()})</p>
<table><tr><th></th>{head}</tr>{summary}</table>
<table><tr><th>#</th><th>유형</th><th>질문</th>{head}</tr>{rows}</table>
<p>✓ 정답 · △ 실행은 되나 결과 다름 · ✕ 서버가 거부하거나 쿼리 없음</p>"""
    os.makedirs(out_dir, exist_ok=True)
    open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8").write(page)
    with open(os.path.join(out_dir, "results.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["질문", "유형", "시스템", "결과", "사유", "결과 행수", "추출한 쿼리"])
        for q in questions:
            for n in names:
                kind, reason, nrows = grades[(q["id"], n)]
                w.writerow([q["id"], q["category"], n, kind, reason, nrows, extract_query(systems[n].get(q["id"], ""))])


def run(answers_dir, out_dir, order):
    questions = load_questions()
    systems = load_answers(answers_dir)
    if not systems:
        sys.exit(f"{answers_dir} 에 답변 파일(*.md)이 없습니다.")
    if order:
        systems = {n: systems[n] for n in order.split(",")}
    gold = {}
    for q in questions:
        rows, err = run_query(q["gold_query"])
        if err or not rows:
            sys.exit(f"{q['id']} 정답 쿼리 실행 실패({err or '결과 없음'}). 먼저 python evaluate.py setup 을 실행하세요.")
        gold[q["id"]] = rows
    grades = {(q["id"], n): grade(extract_query(a.get(q["id"], "")), gold[q["id"]]) for q in questions for n, a in systems.items()}
    write_report(questions, systems, grades, out_dir)
    print("| 시스템 | 실행 성공 | 정답 | 오류 |\n| --- | --- | --- | --- |")
    for n in systems:
        c = lambda *k: sum(1 for q in questions if grades[(q["id"], n)][0] in k)
        print(f"| {n} | {c('정답', '결과 다름')}/{len(questions)} | {c('정답')}/{len(questions)} | {c('오류', '쿼리 없음', '차단')}/{len(questions)} |")
    print("리포트:", os.path.join(out_dir, "report.html"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["setup", "questions", "run"])
    ap.add_argument("--answers", default=os.path.join(HERE, "answers"), help="답변 파일 폴더")
    ap.add_argument("--out", default=os.path.join(HERE, "results"), help="결과 저장 폴더")
    ap.add_argument("--order", help="리포트 열 순서 (예: gpt,gemini,llm_only,agent_rag)")
    a = ap.parse_args()
    if a.command == "questions":
        for q in load_questions():
            print(f"### {q['id']}\n{q['question']}\n")
    else:
        if not KEY:
            sys.exit("환경변수 LOGPRESSO_API_KEY 가 필요합니다.")
        setup() if a.command == "setup" else run(a.answers, a.out, a.order)
