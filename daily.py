# -*- coding: utf-8 -*-
"""
등대 daily v1 — 일일 AI 요약관
- collector 원자료를 AI가 읽고 "오늘 무엇이 있었고 왜 중요한가"를 보고서로 쓴다.
- 판단은 사용자 몫. AI는 재료를 정리·선별하고 근거를 붙인다.
- 비용 안전장치: 하루 1회 · 월 상한 · 사용량/비용 표시
"""
import os, json, glob
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

CONSTITUTION = """너는 투자자를 위해 하루치 공시·정책 자료를 정리하는 분석관이다.
읽는 사람은 이 보고서만 읽고 판단한다. 원문을 다시 찾아보게 만들면 실패다.

절대 규칙 — 뭉뚱그리지 말 것:
- **고유명사는 반드시 풀어 쓴다.** "7대 미래성장동력에 SMR 포함"이 아니라
  "정부가 7대 미래성장동력(반도체·바이오·SMR·양자·우주·전력망·로봇)을 선정했고, 그중 SMR에는 OO억원이 배정"처럼 목록과 숫자를 다 쓴다.
  재료에 목록이 없으면 "목록은 재료에 없음"이라고 밝힌다.
- **회사가 나오면 무엇을 하는 회사인지 한 줄로 설명한다.** 재료의 업종·주요제품 정보를 쓰고, 없으면 "사업 내용 미확인"이라고 쓴다.
- **공시는 숫자를 그대로 옮긴다.** "자사주 취득"이 아니라 "자사주 114,416주·50억원 취득, 목적은 주가 변동성 완화와 소각을 통한 주주가치 제고".
- **"~관련 이벤트가 다수"처럼 뭉뚱그리지 않는다.** 몇 건인지, 어느 회사인지, 어떤 내용인지 쓴다.
- 정책은 무엇이 어떻게 바뀌는지, 언제부터인지, 어느 산업·어떤 종류의 기업에 닿는지 쓴다.

기본 규칙:
1. 재료에 없는 사실을 주장하지 않는다. 배경지식은 [기억] 태그, 확신 없으면 "모른다"라고 쓴다.
2. 모든 주장 문장에 근거 번호를 붙인다: [12] 처럼.
3. 매수·매도·보유·유망 등 투자 추천 표현 금지. "무엇이 있었고 왜 중요한가"까지만.
4. **선별이 핵심 임무다.** 투자와 무관한 것(행정 절차, 지역 행사, 외국 문화재 규정, 정치 공방)은 버린다. 버린 것은 언급하지 않는다.
5. 한국어로 쓴다. 영문 자료는 자연스럽게 옮기되 기관명은 관례 표기를 쓴다.
6. 재료가 얇은 날은 "오늘은 큰 흐름이 없다"가 성과다. 억지로 채우지 않는다.
7. 같은 사안이 여러 건이면 하나로 묶되, 묶은 것들의 차이(금액이 다르면 각각의 금액)를 밝힌다.

출력 형식 — "# 오늘의 보고" 로 시작하고 순서를 지킨다:

# 오늘의 보고
## 한 줄 요약
(오늘 가장 중요한 것 한두 문장. 고유명사는 풀어서)

## ⭐ 감시 대상
(워치리스트 종목·주제 관련. 각 항목을 **문단으로** 쓴다 — 무슨 일이 있었고, 숫자가 얼마이고, 왜 중요한가)

## 주목할 공시
(위험·의지·실체·자본·지분 순. 각 항목:
 **회사명 (업종·주요제품) — 공시 유형**
 무슨 내용인지 숫자와 목적을 포함해 2~4문장. 왜 중요한지 한 문장. [번호])
(최대 10건. 중요도 낮으면 넣지 않는다)

## 정책·환경 변화
(각 항목: 무엇이 어떻게 바뀌는가(구체적으로) · 규모·금액 · 시행일 · 어느 산업에 닿는가 · [번호])
(최대 6건)

## 내일 이후 주시할 것
(예정 일정, 이어질 사안)

## 모른다
(재료로 판단할 수 없었던 것. 무엇을 더 확인해야 하는지)

말미: "그물 범위: [원천 목록] · [기준 시각]. 여기 없는 정보는 존재할 수 있음."
"""

def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[알림 생략] 텔레그램 미설정"); return
    try:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text[:4000],
                            "disable_web_page_preview": True}, timeout=20).raise_for_status()
        print("[알림 OK]")
    except Exception as e:
        print(f"[알림 FAIL] {type(e).__name__}: {str(e)[:120]}")

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
        head = f"[{n}] ({k}|{s}|{src}{'|'+w if w else ''}) {x['core'][:110]}{prof}"
        ab = (x.get("abstract") or "").strip().replace("\n", " ")
        if ab:
            head += f"\n    {ab[:220]}"
        if x.get("effective"):
            head += f"\n    시행일: {x['effective']}"
        lines.append(head)
        x["_no"] = n
    return "\n".join(lines), items

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "")        # 비우면 자동 탐색
GEMINI_THINK = os.environ.get("GEMINI_THINK", "1") != "0"  # 확장 사고 사용

# 선호 순서: 상위 → 하위 (무료로 열리는 것 중 가장 좋은 것을 고른다)
# 등급: 이름에 들어간 단어로 계열을 판정 (새 모델명이 나와도 통함)
TIER = [("ultra", 60), ("pro", 55), ("flash", 40), ("lite", 15)]

def _score(name):
    """무료로 쓸 수 있는 것 중 가장 좋은 모델을 고르기 위한 점수.
    계열(pro>flash>lite) + 세대 번호(높을수록) 조합. 미래 버전도 자동 인식."""
    n = name.lower()
    base = 35                                   # 정체불명 모델의 기본점
    for key, sc in TIER:
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
    """사용 가능한 모델 목록 조회 → (이름, 출력한도, 점수) 정렬"""
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

    for c in cands[:4]:            # 위에서부터 시도, 막히면 다음 모델로
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
                print(f"[{c['name']} 실패 {r.status_code}] {r.text[:160]}")
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
    tail = (f"\n💰 {cost:,.0f}원" if cost else "\n💰 무료(Gemini)") + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회"
    send_telegram(f"🗼 {d['date']} 등대 보고\n\n{report[:1500]}{link}{tail}")

if __name__ == "__main__":
    main()
