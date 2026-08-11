# -*- coding: utf-8 -*-
"""
분석관 p4.2 — 주간 보고서 (실패 시 텔레그램 경고): 워치리스트 ⭐ + 개방형 산업 분류. 상한 6000.
역할: 분석관(Opus 5)=요약 작성만 / 검토관(Fable 5)=누락 검사·수정 명령 / 판단=사용자.
"""
import os, json, glob
from datetime import datetime, timezone, timedelta
import requests

KST = timezone(timedelta(hours=9))
API_URL = "https://api.anthropic.com/v1/messages"
EXECUTOR = "claude-opus-5"
ADVISOR = "claude-fable-5"
BETA = "advisor-tool-2026-03-01"
MARK = "# 주간 보고서"

CONSTITUTION = """너는 정책·공시 브리핑을 요약·정리해 주간 보고서를 쓰는 분석관이다. 규칙:
1. 재료에 없는 사실을 주장하지 않는다. 배경지식은 [기억] 태그, 확신 없으면 "모른다"라고 쓴다.
2. 모든 주장 문장에 태그: [재료N], [기억], [짐작]. 해석·평가·전망을 만들지 않는다 — 빈도·반복·예고 일정 등 재료가 직접 보여주는 것만 정리한다.
3. 언론보도 경유와 공식 원문을 구분한다.
4. 매수·매도·보유·유망 등 투자 추천 표현 금지.
5. 전수 나열 금지: 군집·중요 항목 중심으로 압축하고, 사소한 항목은 각 분류 말미에 "기타:" 한 줄로 묶는다. 얇은 주는 "큰 흐름이 없다"가 성과다.
6. 보고서 전문을 한국어로 쓴다. 영어 재료는 자연스러운 한국어로 번역 서술하되 [재료N] 번호를 유지하고, 기관명은 한국어 관례 표기(상무부, 연준 등)로 쓴다.
7. 작성 순서: 다룰 분류의 커버리지 목록을 짧게 쓴다 → 반드시 advisor를 호출해 누락 검사를 받는다 → 지적을 재료에서 찾아 반영한 최종본을 낸다.
8. 최종 보고서는 "# 주간 보고서"로 시작하고 구성은:
   [⭐ 워치리스트] 제공된 감시어 관련 항목 전부. 없으면 "관련 소식 없음(재료 기준 확인)".
   [분류별 정리] 표준 분류(관련 재료가 있는 것만 섹션 생성): 반도체/AI · 전력/원자력 · 조선/해운 · 항공/물류 · 원유/가스 · 금속/광물 · 2차전지/ESS · 자동차/모빌리티 · 방산/우주 · 바이오/제약 · 금융/보험 · 핀테크/가상자산 · 건설/부동산 · 화학/소재 · 유통/소비재 · 식품/농업 · 엔터/미디어/게임 · 통신/플랫폼 · 로봇/자동화 · 관세/무역 · 금리/통화 · 세제/보조금. 재료에 등장하나 이 목록에 없는 산업은 새 섹션을 신설한다.
   [다음 주 일정] 재료에 예고된 발표·시한의 D-day 정리.
   [모른다 목록] 재료로 답이 안 나온 열린 질문.
   [검토관 검수 결과] 지적 목록 + 반영 내역. 지적 없으면 "검수 통과, 지적 없음".
   말미 필수: "그물 범위: [원천 목록], [기간]. 여기 없는 정책·공시는 존재할 수 있다."
"""

ADVISOR_LINE = ("(Advisor: 너의 유일한 임무는 완결성 검사다. 아래 재료 전체와 실행자의 "
                "커버리지 목록을 대조해, 빠진 중요 항목의 재료 번호만 지적하라. "
                "새 해석·새 지식 추가 금지. 80단어 이내.)")

def send_telegram(text):
    token, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[알림 생략] 텔레그램 미설정"); return
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status(); print("[알림 OK]")
    except Exception as e:
        print(f"[알림 FAIL] {type(e).__name__}: {str(e)[:120]}")

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
    prompt = (f"{ADVISOR_LINE}\n\n[워치리스트(강조 감시어): {wl_line}]\n"
              f"[재료: 최근 브리핑 모음, 항목 {count}건, 기간 {period}]\n"
              f"{material}\n\n지시: 위 재료로 이번 주 주간 보고서를 작성하라. "
              f"헌법의 작성 순서(커버리지 목록 → advisor 누락 검사 → 반영 → 최종본)를 따르라.")
    messages = [{"role": "user", "content": prompt}]

    all_blocks, resp = [], None
    for i in range(4):  # pause_turn 재개 대비
        resp = call_api(messages)
        all_blocks += resp.get("content", [])
        print(f"[턴 {i+1}] stop={resp.get('stop_reason')} usage={json.dumps(resp.get('usage', {}))[:300]}")
        if resp.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": resp["content"]})
            continue
        break

    texts = "\n".join(b.get("text", "") for b in all_blocks if b.get("type") == "text")
    idx = texts.rfind(MARK)
    report = texts[idx:] if idx != -1 else texts
    reviewed = any(b.get("type") == "advisor_tool_result"
                   and isinstance(b.get("content"), dict)
                   and b["content"].get("type") in ("advisor_result", "advisor_redacted_result")
                   for b in all_blocks)
    if not reviewed:
        report += "\n\n⚠️ 검수 미수행 — 검토관 호출이 실패했거나 이루어지지 않았습니다."
    if resp and resp.get("stop_reason") == "max_tokens":
        report += "\n\n⚠️ 길이 상한(6000토큰)에서 잘림 — 상한 조정이 필요합니다."

    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    header = f"> 생성: {stamp} KST · 분석관 {EXECUTOR} · 검토관 {ADVISOR} · 재료 {count}건 ({period})\n\n"
    final = header + report
    os.makedirs("briefing/reports", exist_ok=True)
    with open("briefing/report_latest.md", "w", encoding="utf-8") as f:
        f.write(final)
    with open(f"briefing/reports/{datetime.now(KST).strftime('%Y-%m-%d')}.md", "w", encoding="utf-8") as f:
        f.write(final)
    print("보고서 저장 완료")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    link = f"\n전문: https://github.com/{repo}/blob/main/briefing/report_latest.md" if repo else ""
    send_telegram(f"📊 주간 보고서 ({period})\n\n{report[:1400]}{link}")

def main():
    try:
        _main()
    except Exception as e:
        msg = f"⚠️ 주간 보고 실패: {type(e).__name__}: {str(e)[:200]}"
        print(msg)
        send_telegram(msg + "\nAPI 크레딧 잔액 또는 Actions 로그를 확인하세요.")

if __name__ == "__main__":
    main()
