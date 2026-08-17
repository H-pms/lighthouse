# -*- coding: utf-8 -*-
"""
분석관 p4.2 — 주간 보고서 (실패 시 텔레그램 경고): 워치리스트 ⭐ + 개방형 산업 분류. 상한 6000.
역할: 분석관(Opus 5)=요약 작성만 / 검토관(Fable 5)=누락 검사·수정 명령 / 판단=사용자.
"""
import os, re, json, glob, time
from datetime import datetime, timezone, timedelta
import requests

KST = timezone(timedelta(hours=9))
API_URL = "https://api.anthropic.com/v1/messages"
EXECUTOR = "claude-opus-5"
ADVISOR = "claude-fable-5"
BETA = "advisor-tool-2026-03-01"
MARK = "# 주간 보고서"
MONTH_LIMIT = int(os.environ.get("REPORT_MONTH_LIMIT", "8"))   # 월 최대 실행 횟수

CONSTITUTION = """너는 투자자의 환경 변수 대응을 돕는 주간 분석관이다.
일일 보고들을 모아 **한 주의 흐름**을 읽는다. 하루짜리 사건이 아니라 며칠에 걸친 궤적을 본다.

**핵심 임무: 사건을 나열하지 말고, 사슬과 흐름을 그려라.**
"무엇이 있었다"가 아니라 "무엇이 어디로 가고 있으며, 그래서 어디에 닿는가"를 쓴다.

## 주간 분석의 세 축

### 1) 이어짐 — 한 주 동안 무엇이 진행됐는가
같은 사안이 여러 날에 걸쳐 나타났다면 그 궤적을 그린다.
  · 단계 이동: 논의 → 예고 → 확정 → 시행 / 계약 → 착공 → 가동
  · 속도: 몇 주째인가, 빨라지는가 느려지는가, 정체됐는가
  · 정체도 정보다. "3주째 논의 단계에 머묾"은 실행 의지가 약하다는 신호일 수 있다.

### 2) 사슬 — 그래서 어디에 닿는가 (최대 3단계)
  1차 → 직접 효과 (가격·비용·수량·규제 요건 중 무엇이 달라지는가)
  2차 → 닿는 산업과 기업 유형. **수혜와 피해를 모두** 쓴다.
  3차 → 그다음 ([짐작] 태그 필수)
  시점 → 언제쯤 실물에 나타나는가, 근거와 함께
  검증 지점 → **이 사슬이 진행 중인지 확인할 관측 대상**. 없으면 사슬은 공상이다.
3단계를 넘기지 마라. 근거가 없으면 "1차까지만 확인 가능"이라고 쓴다.

### 3) 판 — 여러 사안을 관통하는 흐름
개별 사슬을 넘어, 이번 주 재료 전체에서 **반복되는 방향**이 있는가.
  · 여러 산업에서 같은 종류의 움직임이 보이는가
  · 그것들의 공통 뿌리는 무엇인가
  · 그 뿌리가 성숙하면 다음에 무엇이 오는가 ([짐작])
관통하는 흐름이 없으면 "이번 주는 개별 사안뿐, 관통하는 흐름 없음"이라고 쓴다.

## 자체 검수 (필수)
초안을 쓴 뒤 스스로 점검하고 최종본을 낸다:
  · 재료에 있는데 빠뜨린 중요 항목은 없는가 (특히 **불리한 것**을 빠뜨렸는지)
  · 사슬의 각 단계에 근거가 붙어 있는가
  · 수혜만 쓰고 피해를 안 썼는가
  · 재료에 없는 사실을 단언하지 않았는가
점검에서 고친 것이 있으면 말미의 [검수 기록]에 적는다.

## 기본 규칙
1. 재료에 없는 사실을 주장하지 않는다. 배경지식은 [기억], 확신 없으면 "모른다".
2. 모든 주장에 근거 번호 [12]. 추론에는 [짐작].
3. 매수·매도·보유·유망 등 투자 추천 금지. 사슬과 검증 지점까지만.
4. 선별이 임무다. 투자와 무관한 것은 버린다.
5. 고유명사는 풀어 쓴다. 회사가 나오면 무엇을 하는 곳인지 한 줄.
6. 한국어. 얇은 주는 "이번 주는 큰 흐름이 없다"가 성과다.

## 출력 형식 — "# 주간 보고서" 로 시작
# 주간 보고서

## 이번 주 한 문단
(관통하는 흐름 또는 가장 중요한 사슬. 사건이 아니라 방향으로)

## 🌊 이어진 사슬
(한 주 동안 진행된 사안 2~4개. 각각:)
### [사안명]
**궤적** — 며칠에 걸쳐 무엇이 어떻게 진행됐는가 [번호]
**단계** — 지금 어디이며, 이번 주에 이동했는가
**사슬** — 1차 / 2차(수혜·피해) / 3차
**시점** — 언제쯤, 근거는
**검증 지점** — 무엇을 보면 진행 중인지 아는가

## 📈 산업 움직임
(건수·단계 분포의 주간 변화. 무엇이 어디로 가고 있는가)

## ⭐ 감시 대상
(워치리스트 관련. 없으면 "해당 없음")

## 📅 다음 주 일정
(예정된 시행일·발표일. 날짜와 함께)

## ❓ 모른다 / 열린 자물쇠
(사슬을 못 그린 것과 이유. 무엇을 더 확인해야 하는지)

## [검수 기록]
(자체 점검에서 고치거나 보완한 것. 없으면 "점검 완료, 수정 없음")

말미: "그물 범위: [원천] · [기간]. 여기 없는 정보는 존재할 수 있음."
"""

ADVISOR_LINE = ("(Advisor: 너의 유일한 임무는 완결성 검사다. 아래 재료 전체와 실행자의 "
                "커버리지 목록을 대조해, 빠진 중요 항목의 재료 번호만 지적하라. "
                "새 해석·새 지식 추가 금지. 80단어 이내.)")

def _split(text, size=4000):
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > size:
            if buf:
                out.append(buf.rstrip()); buf = ""
            while len(para) > size:
                out.append(para[:size]); para = para[size:]
        buf += para + "\n"
    if buf.strip():
        out.append(buf.rstrip())
    return out

def send_telegram(text, parts=1):
    import time as _t
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[알림 생략] 텔레그램 미설정"); return
    chunks = _split(text)[:max(1, parts)]
    for i, c in enumerate(chunks, 1):
        tag = f"\n\n({i}/{len(chunks)})" if len(chunks) > 1 else ""
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": (c + tag)[:4000],
                                    "disable_web_page_preview": True}, timeout=20)
            r.raise_for_status(); print(f"[알림 OK {i}/{len(chunks)}]")
        except Exception as e:
            print(f"[알림 FAIL] {type(e).__name__}: {str(e)[:120]}"); return
        if i < len(chunks):
            _t.sleep(1.2)

def load_material(days=7):
    files = sorted(glob.glob("briefing/history/*.md"))[-days:]
    if not files:
        return None, 0, ""
    parts, n = [], 0
    for fp in files:
        date = os.path.basename(fp)[:-3]
        out = [f"=== {date} ==="]
        with open(fp, encoding="utf-8") as f:
            for line in f:
                s = line.rstrip("\n")
                if s.startswith("- "):
                    n += 1
                    s = f"{n}. {s[2:]}"
                out.append(s)
        parts.append("\n".join(out))
    period = f"{os.path.basename(files[0])[:-3]} ~ {os.path.basename(files[-1])[:-3]}"
    return "\n\n".join(parts), n, period

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")
GEMINI_THINK = os.environ.get("GEMINI_THINK", "1") != "0"
FREE_FIRST = os.environ.get("GEMINI_FREE_FIRST", "1") != "0"
TIER_FREE = [("flash", 55), ("ultra", 25), ("pro", 20), ("lite", 15)]
TIER_PERF = [("ultra", 60), ("pro", 55), ("flash", 40), ("lite", 15)]

def _score(name):
    n = name.lower()
    base = 35
    for key, sc in (TIER_FREE if FREE_FIRST else TIER_PERF):
        if key in n:
            base = sc
            break
    if "lite" in n:
        base = min(base, 15)
    v = re.search(r"gemini[-_]?(\d+(?:\.\d+)?)", n)
    gen = 0.0
    if v:
        try:
            gen = float(v.group(1))
        except Exception:
            gen = 0.0
    elif "latest" in n:
        gen = 3.0
    base += gen * 6
    if "preview" in n or "-exp" in n:
        base -= 4
    if "thinking" in n:
        base += 3
    return max(base, 1)

def gemini_models(key):
    try:
        r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                         params={"key": key, "pageSize": 200}, timeout=30)
        if r.status_code != 200:
            print(f"[모델 목록 실패 {r.status_code}] {r.text[:150]}")
            return []
        out = []
        for m in r.json().get("models", []):
            name = m.get("name", "").replace("models/", "")
            if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                continue
            if not name.startswith("gemini"):
                continue
            if any(k in name.lower() for k in ("embedding", "aqa", "vision-", "image", "tts", "live")):
                continue
            out.append({"name": name, "max_out": int(m.get("outputTokenLimit") or 8192),
                        "score": _score(name)})
        out.sort(key=lambda x: (-x["score"], -x["max_out"]))
        return out
    except Exception as e:
        print(f"[모델 목록 오류] {type(e).__name__}")
        return []

def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    cands = ([{"name": GEMINI_MODEL, "max_out": 16000}] if GEMINI_MODEL
             else gemini_models(key) or [{"name": "gemini-flash-latest", "max_out": 8192}])
    if not GEMINI_MODEL:
        print("[모델 후보] " + " > ".join(f"{c['name']}({c['max_out']})" for c in cands[:5]))
    for c in cands[:8]:
        cap = min(int(c.get("max_out") or 8192), 32768)
        gen = {"maxOutputTokens": cap, "temperature": 0.3}
        if GEMINI_THINK:
            gen["thinkingConfig"] = {"thinkingBudget": -1}
        body = {"systemInstruction": {"parts": [{"text": CONSTITUTION}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{c['name']}:generateContent"
        for attempt in (1, 2, 3):
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=900)
                if r.status_code == 200:
                    j = r.json()
                    cand = (j.get("candidates") or [{}])[0]
                    parts = (cand.get("content") or {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    if not text.strip():
                        print(f"[{c['name']}] 빈 응답"); break
                    um = j.get("usageMetadata") or {}
                    return {"text": text, "cost": 0.0,
                            "provider": f"Gemini({c['name']}{'·사고' if um.get('thoughtsTokenCount') else ''})",
                            "usage": {"input_tokens": um.get("promptTokenCount", 0),
                                      "output_tokens": um.get("candidatesTokenCount", 0),
                                      "thinking_tokens": um.get("thoughtsTokenCount", 0)}}
                if r.status_code == 400 and "thinking" in r.text.lower() and attempt == 1:
                    gen.pop("thinkingConfig", None); body["generationConfig"] = gen
                    continue
                if r.status_code in (500, 502, 503, 504) and attempt == 1:
                    print(f"[{c['name']}] 일시 혼잡({r.status_code}) - 8초 후 재시도")
                    time.sleep(8)
                    continue
                why = "무료 한도 없음/초과" if r.status_code == 429 else \
                      ("모델 없음" if r.status_code == 404 else r.text[:100])
                print(f"[{c['name']} 실패 {r.status_code}] {why}")
                break
            except Exception as e:
                print(f"[{c['name']} 오류] {type(e).__name__}"); break
    return None

def call_api(messages):
    body = {"model": EXECUTOR, "max_tokens": 6000, "system": CONSTITUTION,
            "tools": [{"type": "advisor_20260301", "name": "advisor",
                       "model": ADVISOR, "max_tokens": 2048, "max_uses": 2}],
            "messages": messages}
    r = requests.post(API_URL, timeout=900, json=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "anthropic-beta": BETA, "content-type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
    return r.json()

def _main():
    force = os.environ.get("FORCE_REPORT", "").lower() in ("1", "true", "yes")
    okg, st = guard_check(force)
    if not okg:
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[생략] ANTHROPIC_API_KEY 미설정")
        send_telegram("⚠️ 주간 보고 생략: API 키가 금고에 없습니다 (ANTHROPIC_API_KEY)")
        return
    material, count, period = load_material()
    if material is None:
        print("[생략] 보관함 비어 있음")
        send_telegram("⚠️ 주간 보고 생략: 보관함이 비어 있습니다 (collector p3 교체 후 다음 주부터)")
        return

    try:
        wl = [s.strip() for s in open("watchlist.txt", encoding="utf-8")
              if s.strip() and not s.strip().startswith("#")]
    except FileNotFoundError:
        wl = []
    wl_line = ", ".join(wl) if wl else "없음"
    prompt = ("[워치리스트(강조 감시어): " + wl_line + "]\n"
              f"[재료: 한 주치 일일 보고 모음, 항목 {count}건, 기간 {period}]\n"
              f"{material}\n\n지시: 위 재료로 이번 주 주간 보고서를 작성하라. "
              "사건 나열이 아니라 이어짐·사슬·관통하는 흐름을 그려라. "
              "초안 후 자체 검수를 거쳐 최종본만 출력하라.")

    # 1순위: Gemini 무료
    got = call_gemini(prompt)
    if got:
        texts, usage, cost = got["text"], got["usage"], 0.0
        provider = got["provider"]
        resp = None
        idx = texts.rfind(MARK)
        report = texts[idx:] if idx != -1 else texts
    else:
        # 2순위: Claude (유료 폴백)
        messages = [{"role": "user", "content": prompt}]
        all_blocks, resp = [], None
        for i in range(4):
            resp = call_api(messages)
            all_blocks += resp.get("content", [])
            print(f"[턴 {i+1}] stop={resp.get('stop_reason')}")
            if resp.get("stop_reason") == "pause_turn":
                messages.append({"role": "assistant", "content": resp["content"]})
                continue
            break
        texts = "\n".join(b.get("text", "") for b in all_blocks if b.get("type") == "text")
        idx = texts.rfind(MARK)
        report = texts[idx:] if idx != -1 else texts
        usage = {}
        u = (resp or {}).get("usage") or {}
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
            if u.get(k):
                usage[k] = u[k]
        provider = f"Claude({EXECUTOR})"
        if resp and resp.get("stop_reason") == "max_tokens":
            report += "\n\n[!] 길이 상한에서 잘림 - 상한 조정 필요"
        cost = est_cost(usage)
    guard_record(st, usage)
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    header = (f"> 생성: {stamp} KST · 모델 {provider} · 재료 {count}건 ({period})\n"
              f"> 사용 토큰: 입력 {usage.get('input_tokens',0):,} · 출력 {usage.get('output_tokens',0):,}"
              + (f" · 사고 {usage['thinking_tokens']:,}" if usage.get("thinking_tokens") else "")
              + (f" · 추정 비용 약 {cost:,.0f}원" if cost else " · 무료")
              + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회\n\n")
    final = header + report
    os.makedirs("briefing/reports", exist_ok=True)
    with open("briefing/report_latest.md", "w", encoding="utf-8") as f:
        f.write(final)
    with open(f"briefing/reports/{datetime.now(KST).strftime('%Y-%m-%d')}.md", "w", encoding="utf-8") as f:
        f.write(final)
    print("보고서 저장 완료")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    link = f"\n전문: https://github.com/{repo}/blob/main/briefing/report_latest.md" if repo else ""
    tail = (f"\n\n💰 {cost:,.0f}원" if cost else f"\n\n💰 무료({provider})") + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회"
    send_telegram(f"📊 주간 보고서 ({period})\n\n{report}{link}{tail}", parts=3)

# ══════════ 비용 안전장치 ══════════
GUARD = "briefing/.last_report.json"

def guard_check(force=False):
    """같은 날 중복 실행·과다 호출을 막는다. (통과=True)"""
    today = datetime.now(KST).strftime("%Y-%m-%d")
    month = today[:7]
    st = {"last_date": None, "month": month, "count": 0, "runs": []}
    if os.path.exists(GUARD):
        try:
            st.update(json.load(open(GUARD, encoding="utf-8")))
        except Exception:
            pass
    if st.get("month") != month:      # 달이 바뀌면 카운터 초기화
        st = {"last_date": st.get("last_date"), "month": month, "count": 0, "runs": []}

    if not force and st.get("last_date") == today:
        msg = (f"⏭ 주간 보고 건너뜀 — 오늘({today}) 이미 생성했습니다.\n"
               f"다시 만들려면 Run workflow 에서 force 를 켜세요.")
        print(msg); send_telegram(msg)
        return False, st
    if st.get("count", 0) >= MONTH_LIMIT:
        msg = (f"🛑 주간 보고 중단 — 이번 달 {st['count']}회로 상한({MONTH_LIMIT}회)에 도달했습니다.\n"
               f"상한은 reporter.py 의 MONTH_LIMIT 에서 조정할 수 있습니다.")
        print(msg); send_telegram(msg)
        return False, st
    return True, st

def guard_record(st, usage=None):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    st["last_date"] = today
    st["count"] = st.get("count", 0) + 1
    st.setdefault("runs", []).append({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
                                      "usage": usage or {}})
    st["runs"] = st["runs"][-30:]
    os.makedirs("briefing", exist_ok=True)
    json.dump(st, open(GUARD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def est_cost(usage):
    """대략 비용(원). 하한 단가 가정이므로 참고용."""
    try:
        i = usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0)
        o = usage.get("output_tokens", 0)
        usd = i / 1e6 * 5 + o / 1e6 * 25      # Opus 4.8 단가 기준(하한 가정)
        return usd * 1400
    except Exception:
        return None


def main():
    try:
        _main()
    except Exception as e:
        msg = f"⚠️ 주간 보고 실패: {type(e).__name__}: {str(e)[:200]}"
        print(msg)
        send_telegram(msg + "\nAPI 크레딧 잔액 또는 Actions 로그를 확인하세요.")

if __name__ == "__main__":
    main()
