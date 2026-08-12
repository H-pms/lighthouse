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
GUARD = "briefing/.last_daily.json"
MARK = "# 오늘의 보고"

CONSTITUTION = """너는 투자자를 위해 하루치 공시·정책 자료를 정리하는 분석관이다.

규칙:
1. 재료에 없는 사실을 주장하지 않는다. 배경지식은 [기억] 태그, 확신 없으면 "모른다"라고 쓴다.
2. 모든 주장 문장에 근거 번호를 붙인다: [12] 처럼 재료의 번호를 쓴다.
3. 매수·매도·보유·유망 등 투자 추천 표현은 금지. "무엇이 있었고 왜 중요한가"까지만 쓴다.
4. **선별이 핵심 임무다.** 재료에는 투자와 무관한 것이 섞여 있다(행정 절차, 지역 행사,
   외국 문화재 규정, 정치 공방 등). 이런 것은 과감히 버려라. 버린 것은 굳이 언급하지 않는다.
5. 한국어로 쓴다. 영문 자료는 자연스러운 한국어로 옮기되 기관명은 관례 표기를 쓴다.
6. 재료가 얇은 날은 "오늘은 큰 흐름이 없다"라고 쓰는 것이 성과다. 억지로 채우지 않는다.
7. 같은 사안이 여러 건이면 하나로 묶고 "N건 보도"로 표시한다.

출력 형식 — 반드시 "# 오늘의 보고" 로 시작하고 아래 순서를 지킨다:

# 오늘의 보고
## 한 줄 요약
(오늘 가장 중요한 것 한 문장. 없으면 "특별한 흐름 없음")

## ⭐ 감시 대상
(워치리스트 종목·주제 관련 항목. 없으면 "해당 없음")

## 주목할 공시
(위험·의지·실체·자본·지분 순. 각 항목: **회사명 — 무슨 공시** 한 줄 + 왜 중요한지 한 줄 + [번호])
(중요도가 낮으면 넣지 않는다. 최대 8건)

## 정책·환경 변화
(투자에 영향을 줄 정책만. 각 항목: 무엇이 바뀌는가 + 어느 산업에 닿는가 + 시행일 + [번호])
(최대 5건)

## 내일 이후 주시할 것
(예정된 일정, 이어질 사안. 없으면 생략)

## 모른다
(재료로 판단할 수 없었던 것. 없으면 생략)

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
        head = f"[{n}] ({k}|{s}|{src}{'|'+w if w else ''}) {x['core'][:110]}"
        ab = (x.get("abstract") or "").strip().replace("\n", " ")
        if ab:
            head += f"\n    {ab[:220]}"
        if x.get("effective"):
            head += f"\n    시행일: {x['effective']}"
        lines.append(head)
        x["_no"] = n
    return "\n".join(lines), items

def call_api(material, meta):
    body = {"model": MODEL, "max_tokens": 3500, "system": CONSTITUTION,
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
    try:
        resp = call_api(material, meta)
    except Exception as e:
        msg = f"⚠️ 일일 보고 실패: {type(e).__name__}: {str(e)[:200]}"
        print(msg); send_telegram(msg); return

    text = "\n".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
    i = text.rfind(MARK)
    report = text[i:] if i != -1 else text
    usage = {k: v for k, v in (resp.get("usage") or {}).items() if isinstance(v, int)}
    cost = est_cost(usage)
    guard_record(st, usage)

    # 근거 번호를 원문 링크로
    links = []
    for x in items[:200]:
        if x.get("_no") and x.get("link"):
            links.append(f"[{x['_no']}] [{x['core'][:70]}]({x['link']})")
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    head = (f"> 생성 {stamp} KST · 모델 {MODEL} · 재료 {len(items)}건\n"
            f"> 토큰 입력 {usage.get('input_tokens',0):,} · 출력 {usage.get('output_tokens',0):,}"
            + (f" · 약 {cost:,.0f}원" if cost else "")
            + f" · 이번 달 {st['count']}/{MONTH_LIMIT}회\n\n")
    final = head + report + "\n\n---\n<details><summary>근거 자료 원문 링크</summary>\n\n" + \
            "\n".join(links) + "\n\n</details>\n"

    os.makedirs("briefing/history", exist_ok=True)
    open("briefing/env_latest.md", "w", encoding="utf-8").write(final)
    open(f"briefing/history/{d['date']}.md", "w", encoding="utf-8").write(final)
    print(f"일일 보고 생성: {len(final):,}자")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    link = f"\n\n전체: https://github.com/{repo}/blob/main/briefing/env_latest.md" if repo else ""
    tail = f"\n💰 {cost:,.0f}원 · 이번 달 {st['count']}/{MONTH_LIMIT}회" if cost else ""
    send_telegram(f"🗼 {d['date']} 등대 보고\n\n{report[:1500]}{link}{tail}")

if __name__ == "__main__":
    main()
