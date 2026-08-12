# -*- coding: utf-8 -*-
"""
등대 digest v3 — 무료 요약기 (공시 우선 · 유형별 배치)
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

KIND_ORDER = ["위험", "의지", "실체", "자본", "지분", "정책", "일정"]
KIND_LABEL = {
 "위험":"⚠️ 위험 신호 — 함정일 수 있는 것",
 "의지":"💪 의지 신호 — 자기 것을 거는 행동",
 "실체":"📊 실체 변화 — 실적·수주",
 "자본":"💧 자본 변동 — 희석·조달",
 "지분":"👤 지분 변동 — 누가 들어오고 나갔나",
 "정책":"🏛 정책·규제 — 환경 변수",
 "일정":"📅 예정 일정 — 다가올 사건",
}
KIND_NOTE = {
 "위험":"소송·손실·거래정지·최대주주 변경 등. 기회보다 함정을 먼저 확인하세요.",
 "의지":"공급계약·시설투자·자사주 취득. 말이 아니라 행동으로 자기 것을 건 사례입니다.",
 "실체":"잠정실적·분기보고서. 인식(주가)이 따라왔는지 대조해 보세요.",
 "자본":"증자·전환사채는 지분 희석, 감자·자사주 소각은 반대 방향입니다.",
 "지분":"5% 이상 대주주 변동과 임원 매매. 매수인지 부여인지 원문에서 확인하세요.",
 "정책":"시행일이 있으면 뒷파도의 도착 시점입니다.",
 "일정":"반증 시한을 정할 때 쓰는 달력입니다.",
}

def build(data):
    items = data.get("items", [])
    ok = [s for s in data["sources"] if s["ok"]]
    bad = [s for s in data["sources"] if not s["ok"]]
    L, T = [], []
    L.append(f"# 환경 브리핑 — {data['date']}")
    L.append(f"> 생성 {data.get('generated','')} KST · 원천 {len(ok)}/{len(data['sources'])} · 수집 {len(items)}건")
    L.append("")
    T.append(f"🗼 등대 {data['date']}")
    if bad:
        L.append("## ⚠️ 수집 실패")
        for s in bad: L.append(f"- **{s['name']}**: {s.get('error','')}")
        L.append("")
        T.append(f"⚠️ 원천 {len(bad)}곳 실패")

    groups = cluster(items)
    packed = []
    for g in groups:
        h = headline(g)
        ks = Counter(k for x in g for k in x.get("kinds", []))
        secs = Counter(s for x in g for s in x.get("sectors", []))
        packed.append({"g": g, "h": h, "n": len(g),
                       "kind": (ks.most_common(1)[0][0] if ks else "기타"),
                       "sec": (secs.most_common(1)[0][0] if secs else ""),
                       "lines": summarize(g, set(words(h["core"]))),
                       "watch": sorted({w for x in g for w in x.get("watch", [])}),
                       "official": any(x.get("official") for x in g),
                       "sym": h.get("symbol", ""), "co": h.get("company", "")})

    # ── 워치리스트 ──
    wl = [p for p in packed if p["watch"] or p["h"].get("org","").endswith("감시종목")]
    L.append(f"## ⭐ 워치리스트 ({len(wl)}건 / 감시어 {len(data.get('watchlist',[]))}개)")
    if wl:
        for p in wl[:12]:
            tag = " · ".join(p["watch"]) or p["co"] or p["sec"]
            L.append(f"- **[{tag}]** [{p['h']['core']}]({p['h']['link']})" + (f" — {p['n']}건" if p["n"]>1 else ""))
            if p["lines"]: L.append(f"  - {p['lines'][0][:170]}")
        T.append(f"⭐ 워치리스트 {len(wl)}건")
        for p in wl[:3]:
            T.append(f"• {p['h']['core'][:54]}")
    else:
        L.append("- 신규 0건 — 위 원천 범위에서 확인됨")
    L.append("")

    # ── 유형별 (투자 의미 순서) ──
    bykind = {}
    for p in packed:
        bykind.setdefault(p["kind"], []).append(p)
    tg_lines = []
    for k in KIND_ORDER:
        ps = bykind.get(k)
        if not ps: continue
        ps.sort(key=lambda p: (0 if p["official"] else 1, -p["n"]))
        L.append(f"## {KIND_LABEL[k]} ({len(ps)}건)")
        L.append(f"<sub>{KIND_NOTE[k]}</sub>")
        L.append("")
        for p in ps[:14]:
            mark = "📄" if p["official"] else "📰"
            meta = []
            if p["sec"]: meta.append(p["sec"])
            if p["h"].get("org"): meta.append(p["h"]["org"])
            if p["n"] > 1: meta.append(f"{p['n']}건 보도")
            if p["h"].get("effective"): meta.append(f"시행 {p['h']['effective']}")
            L.append(f"- {mark} [{p['h']['core']}]({p['h']['link']})"
                     + (f"  \n  <sub>{' · '.join(meta)}</sub>" if meta else ""))
            for s in p["lines"][:2]:
                L.append(f"  > {s}")
        if len(ps) > 14:
            L.append(f"- _외 {len(ps)-14}건_")
        L.append("")
        tg_lines.append((k, len(ps), ps[0]["h"]["core"] if ps else ""))

    etc = bykind.get("기타", [])
    if etc:
        L.append(f"## 그 외 ({len(etc)}건)")
        for p in etc[:8]:
            L.append(f"- {'📄' if p['official'] else '📰'} [{p['h']['core']}]({p['h']['link']})"
                     + (f" — {p['n']}건" if p["n"]>1 else ""))
        L.append("")

    # 텔레그램 본문
    if tg_lines:
        T.append("")
        for k, n, top in tg_lines[:5]:
            T.append(f"{KIND_LABEL[k].split(' — ')[0]} {n}건")
            if top: T.append(f"  · {top[:52]}")

    L.append("---")
    L.append(f"_{data.get('coverage','')}_")
    L.append("_📄 원문 · 📰 보도 · 프로그램이 묶고 추린 것이며 해석·판단이 아닙니다._")
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
