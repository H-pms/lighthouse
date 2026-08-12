# -*- coding: utf-8 -*-
"""
등대 digest v2 — 무료 요약기
- 원자료를 읽어 사안 단위로 묶고, 본문에서 핵심 문장을 뽑아 보고서를 만든다.
- 한 사안은 한 곳에만 배치(주섹터). 중복 출력 없음.
- AI가 아니므로 해석하지 않는다. 묶기·세기·추리기만 한다.
"""
import os, re, json
from datetime import datetime, timezone, timedelta
from collections import Counter

import requests

KST = timezone(timedelta(hours=9))
STOP = set("그 및 등 관련 대한 위한 통한 있다 없다 한다 된다 대해 따라 오늘 내일 어제 올해 지난 이번 "
           "관계자 뉴스 기자 사진 종합 속보 단독 the and for with from that this will has have".split())
CUT = 3   # 사안당 본문 문장 수

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

def words(t):
    return [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", t or "")
            if w.lower() not in STOP and not w.isdigit()]

def cluster(items):
    used, groups = set(), []
    for i, a in enumerate(items):
        if i in used: continue
        wa = set(words(a["core"])); grp = [a]; used.add(i)
        for j, b in enumerate(items):
            if j <= i or j in used: continue
            wb = set(words(b["core"]))
            if not wa or not wb: continue
            inter = wa & wb
            if len(inter) >= 2 and len(inter) / min(len(wa), len(wb)) >= 0.4:
                grp.append(b); used.add(j)
        groups.append(grp)
    return groups

def headline(grp):
    off = [x for x in grp if x.get("official")]
    pool = off or grp
    # 본문이 있는 것 우선, 그다음 짧은 제목
    return sorted(pool, key=lambda x: (0 if x.get("abstract") else 1, len(x["core"])))[0]

def summarize(grp, keyw):
    """군집의 본문에서 핵심어를 많이 담은 문장 CUT개를 뽑는다"""
    pool = []
    for x in grp:
        ab = (x.get("abstract") or "").strip()
        if not ab: continue
        for s in re.split(r"(?<=[.다\?!])\s+", ab):
            s = s.strip()
            if 25 <= len(s) <= 220:
                pool.append((s, x))
    if not pool: return []
    seen, out = set(), []
    scored = []
    for s, x in pool:
        sw = set(words(s))
        score = len(sw & keyw) + (1.2 if x.get("official") else 0)
        scored.append((score, len(s), s))
    scored.sort(key=lambda t: (-t[0], t[1]))
    for _, _, s in scored:
        k = s[:24]
        if k in seen: continue
        seen.add(k); out.append(s)
        if len(out) >= CUT: break
    return out

def build(data):
    items = data.get("items", [])
    ok = [s for s in data["sources"] if s["ok"]]
    bad = [s for s in data["sources"] if not s["ok"]]
    L, T = [], []
    L.append(f"# 환경 브리핑 — {data['date']}")
    L.append(f"> 생성 {data.get('generated','')} KST · 원천 {len(ok)}/{len(data['sources'])} · 수집 {len(items)}건")
    L.append("")
    T.append(f"🗼 등대 브리핑 {data['date']}")
    if bad:
        L.append("## ⚠️ 수집 실패")
        for s in bad: L.append(f"- **{s['name']}**: {s.get('error','')}")
        L.append("")
        T.append(f"⚠️ 원천 {len(bad)}곳 실패")

    # 전체를 사안 단위로 한 번만 묶는다 (섹터 중복 제거)
    groups = cluster(items)
    packed = []
    for g in groups:
        h = headline(g)
        secs = Counter(s for x in g for s in x["sectors"])
        main = secs.most_common(1)[0][0] if secs else "기타"
        keyw = set(words(h["core"]))
        packed.append({"g": g, "h": h, "n": len(g), "sec": main,
                       "secs": [s for s, _ in secs.most_common()],
                       "lines": summarize(g, keyw),
                       "watch": sorted({w for x in g for w in x.get("watch", [])}),
                       "official": any(x.get("official") for x in g)})
    packed.sort(key=lambda p: (-p["n"], 0 if p["official"] else 1))

    # ── 오늘의 요점: 반복이 많거나 공식 원문인 사안 ──
    top = [p for p in packed if p["n"] >= 2 or p["official"]][:6]
    if top:
        L.append("## 오늘의 요점")
        for p in top:
            L.append(f"\n**{p['h']['core']}**  ")
            meta = [f"{p['sec']}"]
            if p["n"] > 1: meta.append(f"{p['n']}개 매체 보도")
            if p["official"]: meta.append("공식 원문")
            if p["h"].get("org"): meta.append(p["h"]["org"])
            L.append(f"<sub>{' · '.join(meta)}</sub>  ")
            for s in p["lines"]:
                L.append(f"> {s}")
            if not p["lines"]:
                L.append("> _본문을 가져오지 못했습니다 — 원문 링크에서 확인하세요._")
            L.append(f"[원문]({p['h']['link']})" +
                     ("".join(f" · [관련{i+1}]({x['link']})" for i, x in enumerate(p['g'][1:4])) if p["n"] > 1 else ""))
        L.append("")

    # ── 워치리스트 ──
    wl = [p for p in packed if p["watch"]]
    L.append(f"## ⭐ 워치리스트 ({len(wl)}개 사안 / 감시어 {len(data.get('watchlist',[]))}개)")
    if wl:
        for p in wl:
            L.append(f"- **[{' · '.join(p['watch'])}]** [{p['h']['core']}]({p['h']['link']})"
                     + (f" — {p['n']}건" if p["n"] > 1 else ""))
            if p["lines"]:
                L.append(f"  - {p['lines'][0][:150]}")
        T.append(f"⭐ 워치리스트 {len(wl)}건")
        for p in wl[:3]:
            T.append(f"• [{'·'.join(p['watch'])}] {p['h']['core'][:50]}")
    else:
        L.append("- 신규 0건 — 위 원천 범위에서 확인됨")
    L.append("")

    # ── 섹터별 (사안은 주섹터에만) ──
    bysec = {}
    for p in packed:
        bysec.setdefault(p["sec"], []).append(p)
    L.append("## 분야별")
    for sec, ps in sorted(bysec.items(), key=lambda kv: -sum(x["n"] for x in kv[1])):
        if sec == "기타": continue
        L.append(f"\n### {sec} — 사안 {len(ps)}개 / 기사 {sum(p['n'] for p in ps)}건")
        for p in ps:
            mark = "📄" if p["official"] else "📰"
            extra = f" _(+{', '.join(p['secs'][1:3])})_" if len(p["secs"]) > 1 else ""
            L.append(f"- {mark} [{p['h']['core']}]({p['h']['link']})"
                     + (f" — {p['n']}건" if p["n"] > 1 else "") + extra)
            if p["lines"] and p not in top:
                L.append(f"  - {p['lines'][0][:160]}")
    etc = bysec.get("기타", [])
    if etc:
        L.append(f"\n### 분류 밖 — {len(etc)}개 사안")
        for p in etc[:10]:
            L.append(f"- {'📄' if p['official'] else '📰'} [{p['h']['core']}]({p['h']['link']})"
                     + (f" — {p['n']}건" if p["n"] > 1 else ""))

    sec_count = Counter()
    for p in packed:
        sec_count[p["sec"]] += p["n"]
    if sec_count:
        T.append("분야: " + " · ".join(f"{s} {n}" for s, n in sec_count.most_common(4)))
    if top:
        T.append("")
        T.append("오늘의 요점:")
        for p in top[:4]:
            head = p["h"]["core"][:44]
            sub = (p["lines"][0][:60] + "…") if p["lines"] else ""
            T.append(f"• {head}" + (f"\n  {sub}" if sub else ""))

    trn = sum(1 for x in items if x.get("translated"))
    L.append("")
    L.append("---")
    L.append(f"_{data.get('coverage','')}_")
    L.append(f"_📄 공식 원문 · 📰 언론 보도 · 영문 {trn}건 한국어 번역_" if trn else
             "_📄 공식 원문 · 📰 언론 보도_")
    L.append("_이 요약은 프로그램이 묶고 추린 것이며 해석·판단이 아닙니다._")

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        T.append("")
        T.append(f"전체: https://github.com/{repo}/blob/main/briefing/env_latest.md")
    return "\n".join(L), "\n".join(T)


def main():
    src = "data/latest.json"
    if not os.path.exists(src):
        print("❌ data/latest.json 없음"); send_telegram("⚠️ 등대: 수집 자료가 없어 브리핑 실패"); return
    data = json.load(open(src, encoding="utf-8"))
    md, tg = build(data)
    os.makedirs("briefing/history", exist_ok=True)
    open("briefing/env_latest.md", "w", encoding="utf-8").write(md)
    open(f"briefing/history/{data['date']}.md", "w", encoding="utf-8").write(md)
    print(f"브리핑 생성: {len(md):,}자")
    send_telegram(tg)


if __name__ == "__main__":
    main()
