# -*- coding: utf-8 -*-
"""
등대 daily v1 — 일일 AI 요약관
- collector 원자료를 AI가 읽고 "오늘 무엇이 있었고 왜 중요한가"를 보고서로 쓴다.
- 판단은 사용자 몫. AI는 재료를 정리·선별하고 근거를 붙인다.
- 비용 안전장치: 하루 1회 · 월 상한 · 사용량/비용 표시
"""
import os, json, glob, time
from datetime import datetime, timezone, timedelta
import requests

KST = timezone(timedelta(hours=9))
API = "https://api.anthropic.com/v1/messages"
MODEL = os.environ.get("DAILY_MODEL", "claude-sonnet-5")
MONTH_LIMIT = int(os.environ.get("DAILY_MONTH_LIMIT", "40"))
MAX_OUT = int(os.environ.get("DAILY_MAX_OUT", "16000"))
COST_CAP = float(os.environ.get("DAILY_COST_CAP", "600"))   # 회당 예상 비용 상한(원)
GUARD = "briefing/.last_daily.json"
MARK = "# 오늘의 보고"

CONSTITUTION = """너는 투자자의 환경 변수 대응을 돕는 분석관이다.

**핵심 임무: 사건을 나열하지 말고, 그 사건이 무엇으로 이어지는지 사슬을 그려라.**
읽는 사람은 "나비가 날갯짓을 했다"가 아니라 "그래서 어디에 태풍이 오는가"를 알아야 한다.
사건만 옮겨 적으면 실패다.

## 연쇄 추론 (가장 중요한 규칙)
중요한 사건마다 반드시 사슬을 그린다. 최대 3단계까지, 각 단계에 근거를 붙인다.

  1차 (직접 효과) — 이 조치로 무엇이 즉시 달라지는가. 가격·비용·수량·규제 요건 중 무엇이.
  2차 (파급) — 그 변화가 어느 산업의 어떤 위치(원료·부품·완제품·설비·서비스)에 닿는가.
      수혜와 피해를 모두 쓴다. 한쪽만 쓰면 틀린 사슬이다.
  3차 (연쇄) — 2차가 실현되면 그다음 무엇이 따라오는가. (여기서부터는 [짐작] 태그 필수)

  시점 — 언제쯤 실물에 나타나는가. 시행일·계약 주기·건설 기간 등 재료에 있는 근거로 추정.
  검증 지점 — **이 사슬이 실제로 진행 중인지 확인할 관측 대상**을 반드시 쓴다.
      예: "OO사의 분기 실적에서 그 부문 매출", "관련 수주 공시", "해당 원자재 가격"
      이것이 없으면 사슬은 공상이다.

3단계를 넘기지 마라. 짐작이 짐작을 낳으면 신뢰도가 무너진다.
사슬을 그릴 근거가 없으면 "1차까지만 확인 가능, 그 이후는 모른다"라고 쓴다.

## 사안의 위치 읽기
재료에는 각 항목의 [단계]와 [추적] 정보가 있다.
  단계: 논의 → 예고 → 확정 → 시행 (정책) / 계약 → 착공 → 가동 (사업)
  추적: 이 사안이 몇 주째인지, 단계가 이동했는지
**단계가 이동한 사안을 우선하라.** 논의가 예고로, 계약이 착공으로 옮겨간 것이 진짜 움직임이다.
같은 자리에 오래 머문 사안은 정체된 것이다 — 그 사실도 정보다.

## 산업 움직임
재료 끝에 [산업 움직임]이 있다. 건수의 증감과 단계 분포의 변화를 보고,
**어느 산업이 어느 방향으로 이동 중인지** 읽어라. 개수가 아니라 변화가 신호다.

## 기본 규칙
1. 재료에 없는 사실을 주장하지 않는다. 배경지식은 [기억], 확신 없으면 "모른다".
2. 모든 주장에 근거 번호 [12]. 추론에는 [짐작] 태그.
3. 매수·매도·보유·유망 등 투자 추천 금지. 사슬과 검증 지점까지만.
4. **선별이 임무다.** 투자와 무관한 것(행정 절차, 지역 행사, 외국 문화재 규정, 정치 공방)은 버린다.
5. 고유명사는 풀어 쓴다. "7대 미래성장동력"이면 목록을 다 쓴다. 없으면 "목록은 재료에 없음".
6. 회사가 나오면 무엇을 하는 회사인지 한 줄. 공시는 숫자와 목적을 그대로.
7. 한국어로 쓴다. 얇은 날은 "오늘은 큰 흐름이 없다"가 성과다.

## 출력 형식 — "# 오늘의 보고" 로 시작
# 오늘의 보고

## 한 줄 요약
(오늘 가장 중요한 사슬 하나를 문장으로. 사건이 아니라 "A → B → C"의 형태로)

## 🌊 오늘의 사슬 (핵심)
(중요한 사건 2~4개. 각각:)
### [사건명]
**무슨 일** — 사실을 숫자와 함께 [번호]
**단계** — 논의/예고/확정/시행 중 어디이며, 지난주 대비 이동했는가
**사슬**
  1차 → (직접 효과)
  2차 → (닿는 산업과 기업 유형, 수혜와 피해 모두)
  3차 → (그다음, [짐작])
**시점** — 언제쯤 실물에 나타나는가, 근거는
**검증 지점** — 무엇을 보면 이 사슬이 진행 중인지 알 수 있는가

## ⭐ 감시 대상
(워치리스트 종목·주제. 없으면 "해당 없음")

## 📋 그 외 공시
(사슬을 그릴 정도는 아니지만 알아야 할 것. 각 한 줄 + [번호])

## 📈 산업 움직임
(건수 변화와 단계 이동. "무엇이 어디로 가고 있는가")

## 📅 다가올 것
(예정 일정, 시행일. 날짜와 함께)

## ❓ 모른다
(사슬을 그릴 수 없었던 것과 그 이유. 무엇을 더 확인해야 하는지)

말미: "그물 범위: [원천] · [기준 시각]. 여기 없는 정보는 존재할 수 있음."
"""
TG_LIMIT = 4000          # 텔레그램 한 통의 최대 길이
TG_PARTS = int(os.environ.get("TELEGRAM_PARTS", "3"))   # 최대 몇 통까지 나눠 보낼지

def _split(text, size=TG_LIMIT):
    """문단·줄 경계를 지켜 나눈다 (단어 중간에서 끊기지 않게)"""
    out, buf = [], ""
    for para in text.split("\n"):
        if len(buf) + len(para) + 1 > size:
            if buf:
                out.append(buf.rstrip()); buf = ""
            while len(para) > size:              # 한 줄이 너무 길면 강제 분할
                out.append(para[:size]); para = para[size:]
        buf += para + "\n"
    if buf.strip():
        out.append(buf.rstrip())
    return out

def send_telegram(text, parts=1):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[알림 생략] 텔레그램 미설정"); return
    chunks = _split(text)[:max(1, parts)]
    for i, c in enumerate(chunks, 1):
        tag = f"\n\n({i}/{len(chunks)})" if len(chunks) > 1 else ""
        body = (c + tag)[:TG_LIMIT]
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": body,
                                "disable_web_page_preview": True}, timeout=20).raise_for_status()
            print(f"[알림 OK {i}/{len(chunks)}]")
        except Exception as e:
            print(f"[알림 FAIL] {type(e).__name__}: {str(e)[:120]}"); return
        if i < len(chunks):
            time.sleep(1.2)      # 연속 발송 간격

# ── 안전장치 ──
def guard_check(force=False):
    today = datetime.now(KST).strftime("%Y-%m-%d"); month = today[:7]
    st = {"last_date": None, "month": month, "count": 0, "runs": []}
    if os.path.exists(GUARD):
        try: st.update(json.load(open(GUARD, encoding="utf-8")))
        except Exception: pass
    if st.get("month") != month:
        st = {"last_date": st.get("last_date"), "month": month, "count": 0, "runs": []}
    if not force and st.get("last_date") == today:
        print("⏭ 오늘 이미 생성 — 건너뜀"); return False, st
    if st.get("count", 0) >= MONTH_LIMIT:
        msg = f"🛑 일일 보고 중단 — 이번 달 {st['count']}회로 상한({MONTH_LIMIT})에 도달"
        print(msg); send_telegram(msg); return False, st
    return True, st

def guard_record(st, usage):
    today = datetime.now(KST).strftime("%Y-%m-%d")
    st["last_date"] = today; st["count"] = st.get("count", 0) + 1
    st.setdefault("runs", []).append({"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "usage": usage})
    st["runs"] = st["runs"][-40:]
    os.makedirs("briefing", exist_ok=True)
    json.dump(st, open(GUARD, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def est_cost(u):
    try:
        i = u.get("input_tokens", 0); o = u.get("output_tokens", 0)
        if "haiku" in MODEL:   rate_i, rate_o = 1, 5
        elif "sonnet" in MODEL: rate_i, rate_o = 3, 15
        else:                   rate_i, rate_o = 5, 25
        return (i/1e6*rate_i + o/1e6*rate_o) * 1400
    except Exception:
        return None

# ── 재료 만들기 ──
def build_material(d):
    """원자료를 번호 붙인 압축 텍스트로 (토큰 절약)"""
    lines, n = [], 0
    order = {"위험":0, "의지":1, "실체":2, "자본":3, "지분":4, "정책":5, "일정":6}
    items = sorted(d["items"], key=lambda x: (order.get((x.get("kinds") or ["정책"])[0], 9),
                                              0 if x.get("watch") else 1))
    for x in items:
        n += 1
        k = "/".join(x.get("kinds") or []) or "-"
        s = "/".join((x.get("sectors") or [])[:2])
        w = "⭐" + ",".join(x["watch"]) if x.get("watch") else ""
        src = "원문" if x.get("official") else "보도"
        prof = f" ⟨{x['profile']}⟩" if x.get("profile") else ""
        st = x.get("stage")
        tr = x.get("track") or {}
        marks = [k, s, src]
        if w: marks.append(w)
        if st: marks.append(f"단계:{st}")
        if tr:
            t = f"{tr.get('weeks','?')}주째·{tr.get('count')}건"
            if tr.get("moved"): t += f"·이동 {tr['moved']}"
            marks.append(t)
        head = f"[{n}] ({'|'.join(m for m in marks if m)}) {x['core'][:110]}{prof}"
        ab = (x.get("abstract") or "").strip().replace("\n", " ")
        if ab:
            head += f"\n    {ab[:220]}"
        if x.get("effective"):
            head += f"\n    시행일: {x['effective']}"
        lines.append(head)
        x["_no"] = n
    return "\n".join(lines), items

def motion_text(mo):
    if not mo:
        return ""
    L = ["", "[산업 움직임 — 이번 주 vs 지난 주]"]
    for m in mo:
        chg = ""
        if m.get("chg") is not None:
            chg = f" ({m['chg']*100:+.0f}%)"
        sn = " ".join(f"{k}{v}" for k, v in sorted(m.get("stages_now", {}).items()))
        sp = " ".join(f"{k}{v}" for k, v in sorted(m.get("stages_prev", {}).items()))
        L.append(f"- {m['sector']}: {m['prev']}건 -> {m['now']}건{chg}"
                 + (f" | 단계 지난주[{sp}] 이번주[{sn}]" if (sn or sp) else ""))
    return "\n".join(L)

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")        # 비우면 자동 탐색
GEMINI_THINK = os.environ.get("GEMINI_THINK", "1") != "0"  # 확장 사고 사용

# 선호 순서: 상위 -> 하위 (무료로 열리는 것 중 가장 좋은 것을 고른다)
# 등급: 무료 티어에서 쓸 수 있는 계열을 우선한다.
# (2026-04 이후 Pro/Ultra 는 무료 티어에서 제외됨 — 유료 결제 시에만 사용 가능)
# FREE_FIRST=0 으로 두면 성능 우선(pro 먼저)으로 바뀐다.
FREE_FIRST = os.environ.get("GEMINI_FREE_FIRST", "1") != "0"
TIER_FREE = [("flash", 55), ("ultra", 25), ("pro", 20), ("lite", 15)]
TIER_PERF = [("ultra", 60), ("pro", 55), ("flash", 40), ("lite", 15)]

def _score(name):
    """무료로 쓸 수 있는 것 중 가장 좋은 모델을 고르기 위한 점수.
    계열(pro>flash>lite) + 세대 번호(높을수록) 조합. 미래 버전도 자동 인식."""
    n = name.lower()
    base = 35                                   # 정체불명 모델의 기본점
    for key, sc in (TIER_FREE if FREE_FIRST else TIER_PERF):
        if key in n:
            base = sc
            break                                # 앞선 계열이 우선 (ultra>pro>flash>lite)
    if "lite" in n:
        base = min(base, 15)
    import re as _re
    v = _re.search(r"gemini[-_]?(\d+(?:\.\d+)?)", n)
    gen = 0.0
    if v:
        try:
            gen = float(v.group(1))
        except Exception:
            gen = 0.0
    elif "latest" in n:
        gen = 3.0                                # 별칭은 중간 세대로 취급
    base += gen * 6                              # 세대가 점수를 지배하도록
    if "preview" in n or "-exp" in n:
        base -= 4
    if "thinking" in n:
        base += 3
    return max(base, 1)

def gemini_models(key):
    """사용 가능한 모델 목록 조회 -> (이름, 출력한도, 점수) 정렬"""
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
            out.append({"name": name,
                        "max_out": int(m.get("outputTokenLimit") or 8192),
                        "max_in": int(m.get("inputTokenLimit") or 32768),
                        "score": _score(name)})
        out.sort(key=lambda x: (-x["score"], -x["max_out"]))
        return out
    except Exception as e:
        print(f"[모델 목록 오류] {type(e).__name__}: {str(e)[:120]}")
        return []

def call_gemini(material, meta):
    """무료 티어 우선 사용. 실패하면 None 반환."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    prompt = (f"[오늘 자료 — {meta['date']} · 원천 {meta['srcs']} · 총 {meta['n']}건]\n"
              f"[워치리스트: {meta['wl']}]\n\n{material}\n\n"
              f"위 재료로 오늘의 보고를 작성하라. 투자와 무관한 항목은 버려라.")

    if GEMINI_MODEL:
        cands = [{"name": GEMINI_MODEL, "max_out": MAX_OUT, "score": 99}]
    else:
        cands = gemini_models(key)
        if cands:
            print("[모델 후보] " + " > ".join(f"{c['name']}({c['max_out']})" for c in cands[:5]))
        else:
            cands = [{"name": "gemini-flash-latest", "max_out": 8192, "score": 0}]

    for c in cands[:8]:            # 위에서부터 시도, 막히면 다음 모델로
        # 출력 한도: 모델이 허용하는 최대치를 따라간다
        cap = min(int(c.get("max_out") or 8192), 32768)
        gen = {"maxOutputTokens": cap, "temperature": 0.3}
        if GEMINI_THINK:
            # 사고 예산: 모델이 지원하면 적용, 아니면 무시됨 (-1 = 모델이 알아서)
            gen["thinkingConfig"] = {"thinkingBudget": -1}
        body = {"systemInstruction": {"parts": [{"text": CONSTITUTION}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": gen}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{c['name']}:generateContent"
        for attempt in (1, 2):
            try:
                r = requests.post(url, params={"key": key}, json=body, timeout=900)
                if r.status_code == 200:
                    j = r.json()
                    cand = (j.get("candidates") or [{}])[0]
                    parts = (cand.get("content") or {}).get("parts", [])
                    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                    if not text.strip():
                        print(f"[{c['name']}] 빈 응답 — 다음 모델 시도"); break
                    um = j.get("usageMetadata") or {}
                    think = um.get("thoughtsTokenCount", 0)
                    return {"text": text, "cost": 0.0,
                            "provider": f"Gemini({c['name']}{'·사고' if think else ''})",
                            "usage": {"input_tokens": um.get("promptTokenCount", 0),
                                      "output_tokens": um.get("candidatesTokenCount", 0),
                                      "thinking_tokens": think, "max_out": cap}}
                # 사고 설정을 못 알아듣는 모델이면 빼고 한 번 더
                if r.status_code == 400 and "thinking" in r.text.lower() and attempt == 1:
                    gen.pop("thinkingConfig", None)
                    body["generationConfig"] = gen
                    print(f"[{c['name']}] 사고 모드 미지원 — 끄고 재시도")
                    continue
                why = "무료 한도 없음/초과" if r.status_code == 429 else \
                      ("모델 없음" if r.status_code == 404 else r.text[:120])
                print(f"[{c['name']} 실패 {r.status_code}] {why}")
                break
            except Exception as e:
                print(f"[{c['name']} 오류] {type(e).__name__}: {str(e)[:120]}")
                break
    return None

def call_api(material, meta):
    body = {"model": MODEL, "max_tokens": MAX_OUT, "system": CONSTITUTION,
            "messages": [{"role": "user", "content":
                f"[오늘 자료 — {meta['date']} · 원천 {meta['srcs']} · 총 {meta['n']}건]\n"
                f"[워치리스트: {meta['wl']}]\n\n{material}\n\n"
                f"위 재료로 오늘의 보고를 작성하라. 투자와 무관한 항목은 버려라."}]}
    r = requests.post(API, timeout=600, json=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01", "content-type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"API {r.status_code}: {r.text[:300]}")
    return r.json()

def main():
    force = os.environ.get("FORCE_DAILY", "").lower() in ("1", "true", "yes")
    ok, st = guard_check(force)
    if not ok: return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[생략] ANTHROPIC_API_KEY 없음")
        send_telegram("⚠️ 일일 보고 생략: API 키가 금고에 없습니다"); return
    if not os.path.exists("data/latest.json"):
        print("[생략] 수집 자료 없음"); send_telegram("⚠️ 일일 보고 생략: 수집 자료 없음"); return

    d = json.load(open("data/latest.json", encoding="utf-8"))
    material, items = build_material(d)
    material += "\n" + motion_text(d.get("motion") or [])
    srcs = ", ".join(s["name"] for s in d["sources"] if s["ok"])
    meta = {"date": d["date"], "srcs": srcs, "n": len(items),
            "wl": ", ".join(d.get("watchlist", [])[:24])}
    # 1순위: Gemini 무료 티어
    got = call_gemini(material, meta)
    provider = None
    if got:
        text, usage, cost, provider = got["text"], got["usage"], 0.0, got["provider"]
    else:
        # 2순위: 클로드 (유료) — 비용 상한 확인
        est_in = int(len(material) / 2.2) + 1200
        pre = est_cost({"input_tokens": est_in, "output_tokens": MAX_OUT})
        if pre and pre > COST_CAP:
            msg = (f"🛑 일일 보고 중단 — 예상 비용 {pre:,.0f}원이 상한({COST_CAP:,.0f}원)을 넘습니다.\n"
                   f"재료가 평소보다 많습니다({len(material):,}자). 상한은 DAILY_COST_CAP 로 조정하세요.")
            print(msg); send_telegram(msg); return
        try:
            resp = call_api(material, meta)
        except Exception as e:
            msg = f"⚠️ 일일 보고 실패: {type(e).__name__}: {str(e)[:200]}"
            print(msg); send_telegram(msg); return
        text = "\n".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        usage = {k: v for k, v in (resp.get("usage") or {}).items() if isinstance(v, int)}
        cost = est_cost(usage)
        provider = f"Claude({MODEL})"
    i = text.rfind(MARK)
    report = text[i:] if i != -1 else text
    if usage.get("output_tokens", 0) >= MAX_OUT - 50:
        report += "\n\n⚠️ 길이 상한에서 잘렸습니다 — DAILY_MAX_OUT 을 늘리세요."
    guard_record(st, usage)

    # 근거 번호를 원문 링크로
    links = []
    for x in items[:200]:
        if x.get("_no") and x.get("link"):
            links.append(f"[{x['_no']}] [{x['core'][:70]}]({x['link']})")
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    head = (f"> 생성 {stamp} KST · 모델 {provider} · 재료 {len(items)}건\n"
            f"> 토큰 입력 {usage.get('input_tokens',0):,} · 출력 {usage.get('output_tokens',0):,}"
            + (f" · 사고 {usage['thinking_tokens']:,}" if usage.get("thinking_tokens") else "")
            + (f" · 약 {cost:,.0f}원" if cost else " · 무료")
            + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회\n\n")
    final = head + report + "\n\n---\n<details><summary>근거 자료 원문 링크</summary>\n\n" + \
            "\n".join(links) + "\n\n</details>\n"

    os.makedirs("briefing/history", exist_ok=True)
    open("briefing/env_latest.md", "w", encoding="utf-8").write(final)
    open(f"briefing/history/{d['date']}.md", "w", encoding="utf-8").write(final)
    print(f"일일 보고 생성: {len(final):,}자")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    link = f"\n\n전체: https://github.com/{repo}/blob/main/briefing/env_latest.md" if repo else ""
    tail = (f"\n💰 {cost:,.0f}원" if cost else f"\n💰 무료({provider})") + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회"
    send_telegram(f"🗼 {d['date']} 등대 보고\n\n{report}{link}{tail}", parts=TG_PARTS)

if __name__ == "__main__":
    main()
