# 쿼리 정확도 비교 (eval)

GPT·Gemini 같은 범용 LLM과 이 에이전트가 만든 로그프레소 쿼리를 **테스트 서버에서 실제로 실행**해 채점합니다.
로그 수집 데이터가 없어도 되도록, 가상 로그를 서버에 직접 넣어서 비교합니다.

## 채점 방식

질문마다 정답 쿼리(`questions.csv`의 `gold_query`)가 있고, 같은 샘플 데이터에 답변 쿼리와 정답 쿼리를 모두 실행해 결과 **값**을 비교합니다. 필드 이름(`count`, `cnt`)은 무시합니다.

| 결과 | 의미 |
|---|---|
| 정답 | 실행 성공 + 결과 값이 정답과 같음 |
| 결과 다름 | 실행은 되지만 필드·조건·집계가 틀려 값이 다름 |
| 오류 | 서버가 거부 (없는 명령어, SQL·Splunk 문법, 옵션·정규식 오류, 없는 테이블) |
| 쿼리 없음 | 답변에서 쿼리를 찾지 못함 |
| 차단 | 서버 데이터를 바꿀 수 있는 명령어(`import`, `output*` 등)라 실행하지 않음 |

문법만 검사하면 놓치는 오류가 있습니다. 예를 들어 없는 필드를 조건으로 쓰면 서버는 오류 없이 0건을 돌려주므로, 결과 비교로만 잡을 수 있습니다.
테이블이 없으면 뒤쪽 명령어의 문법 오류가 가려지기 때문에(`table-not-found`만 나옴) 반드시 샘플 테이블이 있어야 합니다.

## 순서

```bash
set LOGPRESSO_URL=https://<테스트 서버>
set LOGPRESSO_API_KEY=<API 키>

python evaluate.py setup       # 샘플 테이블 eval_fw(60건), eval_web(40건) 새로 만들기
python evaluate.py questions   # 질문 16개 출력 → GPT·Gemini 에 그대로 붙여넣기

# 에이전트와 RAG 없는 같은 모델의 답변 자동 수집 (API 비용 발생)
set ANTHROPIC_API_KEY=<API 키>
python collect_agent.py

python evaluate.py run --order gpt,gemini,llm_only,agent_rag
```

결과는 `results/`에 저장됩니다. `report.html`을 브라우저로 열어 캡처하면 비교표가 됩니다.

- `results/report.html` : 시스템별 요약표 + 문항별 비교표
- `results/results.csv` : 문항·시스템별 결과, 오류 사유, 서버가 실행한 쿼리

## 개선 전후 비교 (v1 → v2)

Q01~Q16 평가에서 에이전트가 정규식 파싱 3문항(Q10~Q12)을 틀렸다. 프롬프트의 문법 요약에 `rex`가 없고, 질문에 "정규식"·"rex"라는 단어가 없어 검색도 rex 문서를 가져오지 못했기 때문이다. 그래서 `prompts.py`의 문법 요약에 `rex`를 추가했다(`prompts_v1.py`는 개선 전 복사본).

- Q10~Q12는 개선의 계기가 된 문항이라 개선 효과의 증거로 쓰지 않는다. 개선하는 동안 보지 않은 **Q17~Q28을 새로 추가**해 v1과 v2를 같은 조건으로 비교한다.
- 문항별 저장 파일: `agent_v1.md`(개선 전), `agent_v2.md`(개선 후), `llm_only.md`(RAG 없음), `gpt.md`, `gemini.md`.

```bash
py collect_agent.py --version v1 --from 17      # 개선 전, 새 문항만
py collect_agent.py --version v2                # 개선 후, 전체
py collect_agent.py --baseline --from 17        # RAG 없는 같은 모델, 새 문항만
python evaluate.py setup
python evaluate.py run --order gpt,gemini,llm_only,agent_v1,agent_v2
```

## 답변 파일 형식

`answers/<시스템 이름>.md` 하나에 문항별 답변을 `### Q01` 제목 아래에 붙여넣습니다. 파일 이름이 리포트의 열 이름이 됩니다.

````
### Q01

```
table duration=1h eval_fw | stats count
```
설명...

### Q02
...
````

답변에서 쿼리는 `<query>` 태그, `<solution>` 안 코드블록, 첫 번째 코드블록 순으로 찾습니다.
코드블록이 없으면 `table`·`system`·`json`으로 시작하는 줄과 그 아래 `|` 줄을 씁니다. 문법 설명용 블록(`table [duration=기간] 테이블이름`처럼 대괄호 안에 한글 자리표시자가 있는 것)은 쿼리로 보지 않고 건너뛰고, 코드블록이 여럿이면 `table`·`system`·`json`으로 시작하는 첫 블록을 씁니다(오류 부위만 보여 주는 조각은 쿼리가 아님).

## 참고

- `setup`은 지금 시각 기준 최근 1시간 로그를 만들므로 **채점 직전에 실행**하세요. 질문이 모두 "최근 1시간"이라 시간이 지나면 정답 쿼리 결과가 달라집니다.
- 서버와 이 PC의 시간대가 같다고 가정합니다 (KST).
- `examples/`는 채점이 동작하는지 확인하려고 만든 **가상 답변**입니다. 실제 LLM 결과가 아니니 비교 자료로 쓰지 마세요.
- 질문 추가: `questions.csv`에 `id, category, title, question, gold_query` 한 줄을 추가하고 정답 쿼리가 샘플 데이터에서 결과를 내는지 `run`으로 확인합니다.
