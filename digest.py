# -*- coding: utf-8 -*-
"""
등대 digest v1 — 무료 요약기 (프로그램 판정)
- collector가 만든 원자료를 읽어 섹터별로 묶고, 중복 군집을 접어 보고서를 만든다.
- 산출물: briefing/env_latest.md (사람용), briefing/history/날짜.md (보관), 텔레그램 발송
- AI가 아니므로 해석하지 않는다. 묶기·세기·접기만 한다.
"""
import os, re, json
from datetime import datetime, timezone, timedelta
from collections import Counter

import requests

KST = timezone(timedelta(hours=9))
STOP = set("그 및 등 관련 대한 위한 통한 있다 없다 한다 된다 대해 따라 오늘 내일 어제 올해 지난 이번 관계자 뉴스 기자 사진 종합 속보 단독".split())

def send_telegram(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[알림 생략] 텔레그램 미설정"); return
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text[:4000],
                                "disable_web_page_preview": True}, timeout=20)
        r.raise_for_status(); print("[알림 OK]")
    except Exception as e:
        print(f"[알림 FAIL] {type(e).__name__}: {str(e)[:120]}")

def words(t):
    return [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", t or "")
            if w not in STOP and not w.isdigit()]

def cluster(items):
    """제목의 공통 핵심어로 같은 사안을 묶는다"""
    used, groups = set(), []
    for i, a in enumerate(items):
        if i in used:
            continue
        wa = set(words(a["core"]))
        grp = [a]; used.add(i)
        for j, b in enumerate(items):
            if j <= i or j in used:
                continue
            wb = set(words(b["core"]))
            if not wa or not wb:
                continue
            inter = wa & wb
            # 핵심어 2개 이상 겹치고, 짧은 쪽 기준 40% 이상 일치
            if len(inter) >= 2 and len(inter) / min(len(wa), len(wb)) >= 0.4:
                grp.append(b); used.add(j)
        groups.append(grp)
    groups.sort(key=lambda g: (-len(g), g[0].get("date", "")))
    return groups

def headline(grp):
    """군집 대표 제목: 가장 짧고 공식 원문 우선"""
    off = [x for x in grp if x.get("official")]
    pool = off or grp
    return sorted(pool, key=lambda x: len(x["core"]))[0]

def build(data):
    items = data.get("items", [])
    L, T = [], []          # L=파일용 마크다운, T=텔레그램용
    now = data.get("generated", "")
    ok = [s for s in data["sources"] if s["ok"]]
    bad = [s for s in data["sources"] if not s["ok"]]

    L.append(f"# 환경 브리핑 — {data['date']}")
    L.append(f"> 생성 {now} KST · 원천 {len(ok)}/{len(data['sources'])} · 항목 {len(items)}건")
    L.append("")
    T.append(f"🗼 등대 브리핑 {data['date']}")

    if bad:
        L.append("## ⚠️ 수집 실패 — 수동 확인 요망")
        for s in bad:
            L.append(f"- **{s['name']}**: {s.get('error','')}")
        L.append("")
        T.append(f"⚠️ 원천 {len(bad)}곳 수집 실패")

    # ── 워치리스트 ──
    wl = [x for x in items if x.get("watch")]
    L.append(f"## ⭐ 워치리스트 ({len(wl)}건 / 감시어 {len(data.get('watchlist',[]))}개)")
    if wl:
        for g in cluster(wl):
            h = headline(g)
            tags = " · ".join(sorted({t for x in g for t in x["watch"]}))
            L.append(f"- **[{tags}]** [{h['core']}]({h['link']})" + (f" — 관련 {len(g)}건" if len(g) > 1 else ""))
        T.append(f"⭐ 워치리스트 {len(wl)}건")
        for g in cluster(wl)[:3]:
            h = headline(g)
            tags = "·".join(sorted({t for x in g for t in x["watch"]}))
            T.append(f"• [{tags}] {h['core'][:52]}" + (f" ({len(g)}건)" if len(g) > 1 else ""))
    else:
        L.append("- 신규 0건 — 위 원천 범위에서 확인됨")
    L.append("")

    # ── 섹터별 묶음 ──
    sec_count = Counter(s for x in items for s in x["sectors"])
    L.append("## 섹터별")
    if sec_count:
        T.append("섹터: " + " · ".join(f"{s} {n}" for s, n in sec_count.most_common(5)))
    big = []
    for sec, n in sec_count.most_common():
        sub = [x for x in items if sec in x["sectors"]]
        groups = cluster(sub)
        L.append(f"\n### {sec} ({n}건, 사안 {len(groups)}개)")
        for g in groups:
            h = headline(g)
            mark = "📄" if h.get("official") else "📰"
            line = f"- {mark} [{h['core']}]({h['link']})"
            if len(g) > 1:
                line += f" — **{len(g)}건 반복**"
                big.append((len(g), sec, h["core"]))
            if h.get("org"):
                line += f" _{h['org']}_"
            L.append(line)
            if len(g) > 1:
                for x in g[1:5]:
                    if x["link"] != h["link"]:
                        L.append(f"  - {x['core'][:70]} [원문]({x['link']})")
    # 미분류
    none = [x for x in items if not x["sectors"]]
    if none:
        L.append(f"\n### 미분류 ({len(none)}건)")
        for g in cluster(none)[:8]:
            h = headline(g)
            L.append(f"- {'📄' if h.get('official') else '📰'} [{h['core']}]({h['link']})"
                     + (f" — {len(g)}건" if len(g) > 1 else ""))

    # 텔레그램: 반복 군집 상위
    big.sort(reverse=True)
    if big:
        T.append("")
        T.append("반복 사안:")
        for n, sec, title in big[:4]:
            T.append(f"• [{sec}] {title[:46]} — {n}건")

    L.append("")
    L.append("---")
    L.append(f"_{data.get('coverage','')}_")
    L.append("_📄=공식 원문 · 📰=언론 보도 · 이 요약은 프로그램이 묶고 센 것이며 해석·판단이 아닙니다._")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        T.append("")
        T.append(f"전체: https://github.com/{repo}/blob/main/briefing/env_latest.md")
    return "\n".join(L), "\n".join(T)


def main():
    src = "data/latest.json"
    if not os.path.exists(src):
        print("❌ data/latest.json 없음 — collector를 먼저 실행하세요")
        send_telegram("⚠️ 등대: 수집 자료가 없어 브리핑을 만들지 못했습니다")
        return
    data = json.load(open(src, encoding="utf-8"))
    md, tg = build(data)
    os.makedirs("briefing/history", exist_ok=True)
    open("briefing/env_latest.md", "w", encoding="utf-8").write(md)
    open(f"briefing/history/{data['date']}.md", "w", encoding="utf-8").write(md)
    print(f"브리핑 생성: {len(md):,}자")
    send_telegram(tg)


if __name__ == "__main__":
    main()
