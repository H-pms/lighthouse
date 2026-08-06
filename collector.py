# -*- coding: utf-8 -*-
"""
정보기관 v0.2a-p1 (패치 1)
- 변경: ① 한국 원천을 구글뉴스 RSS 경유로 교체(공식 피드는 사용자가 주소 제공 시 KR_OFFICIAL_FEEDS에 추가)
        ② 섹터 태그 오탐 수정: 영문 키워드는 단어 경계(word boundary) 매칭 (vessels→ess 오탐 제거)
설계 원칙: 실패는 침묵이 아니라 소음으로.
"""
import os, re
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

KST = timezone(timedelta(hours=9))
UA = "LighthouseIntel/0.2a (personal research bot)"
MAX_PER_SECTION = 12

SECTOR_KEYWORDS = {
    "반도체/AI": ["semiconductor", "chip", "ai", "artificial intelligence", "data center", "반도체", "인공지능", "파운드리", "hbm", "데이터센터"],
    "전력/원자력": ["electric grid", "power plant", "nuclear", "grid", "전력", "송전", "변전", "원전", "smr", "에너지"],
    "냉각/냉매": ["refrigerant", "cooling", "hfc", "냉매", "냉각", "액침"],
    "수출통제/관세": ["export control", "tariff", "sanction", "수출통제", "관세", "제재", "무역"],
    "금리/통화": ["interest rate", "federal reserve", "monetary", "금리", "기준금리", "통화정책", "한국은행"],
    "보조금/세제": ["subsidy", "tax credit", "grant", "보조금", "세액공제", "지원금", "세제"],
    "바이오/의료": ["fda", "drug", "clinical", "바이오", "의약", "임상", "제약"],
    "방산/우주": ["defense", "military", "space", "방위", "방산", "우주"],
    "2차전지/ESS": ["battery", "energy storage", "ess", "이차전지", "배터리", "양극재"],
    "모빌리티": ["vehicle", "automotive", "자동차", "전기차", "자율주행"],
}

def _compile():
    out = {}
    for sec, kws in SECTOR_KEYWORDS.items():
        pats = []
        for k in kws:
            k = k.strip().lower()
            if re.fullmatch(r"[a-z0-9 ]+", k):      # 영문·숫자 → 단어 경계 매칭
                pats.append(re.compile(r"\b" + re.escape(k) + r"\b"))
            else:                                    # 한국어 → 부분 문자열 매칭
                pats.append(re.compile(re.escape(k)))
        out[sec] = pats
    return out

_PATTERNS = _compile()

def tag_sectors(text):
    t = (text or "").lower()
    return [s for s, pats in _PATTERNS.items() if any(p.search(t) for p in pats)]

# ---------------- 원천들 ----------------

def fetch_federal_register():
    r = requests.get(
        "https://www.federalregister.gov/api/v1/documents.json",
        params={"per_page": MAX_PER_SECTION, "order": "newest"},
        headers={"User-Agent": UA}, timeout=30,
    )
    r.raise_for_status()
    items = []
    for d in r.json().get("results", []):
        title = (d.get("title") or "").strip()
        abstract = d.get("abstract") or ""
        items.append({
            "title": title,
            "date": d.get("publication_date", ""),
            "org": ", ".join(a.get("name", "") for a in (d.get("agencies") or [])[:2]),
            "link": d.get("html_url", ""),
            "sectors": tag_sectors(title + " " + abstract),
        })
    if not items:
        raise RuntimeError("응답은 왔으나 문서 0건 — API 형식 변경 의심")
    return items

def fetch_rss(url):
    if not HAS_FEEDPARSER:
        raise RuntimeError("feedparser 미설치")
    f = feedparser.parse(url, agent=UA)
    if not f.entries:
        err = getattr(f, "bozo_exception", "항목 0건")
        raise RuntimeError(f"피드 비었음/오류: {str(err)[:120]}")
    items = []
    for e in f.entries[:MAX_PER_SECTION]:
        title = getattr(e, "title", "").strip()
        summary = getattr(e, "summary", "")
        items.append({
            "title": title,
            "date": getattr(e, "published", getattr(e, "updated", ""))[:16],
            "org": "",
            "link": getattr(e, "link", ""),
            "sectors": tag_sectors(title + " " + summary),
        })
    return items

def gnews(query):
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"

# 공식 피드 주소를 확보하면 아래 목록에 ("이름", "주소") 형태로 추가 — 자동으로 수집에 포함됨
KR_OFFICIAL_FEEDS = [
    # 예: ("🇰🇷 정책브리핑·보도자료(공식)", "https://www.korea.kr/rss/XXXX.xml"),
]

SOURCES = [
    ("🇺🇸 연방관보(공식)", fetch_federal_register),
    ("🇰🇷 경제부처·한은 언론보도(구글뉴스 경유)", lambda: fetch_rss(gnews("기획재정부 OR 산업통상자원부 OR 금융위원회 OR 한국은행 when:2d"))),
    ("🇰🇷 규제·수출통제 언론보도(구글뉴스 경유)", lambda: fetch_rss(gnews("규제 OR 수출통제 OR 관세 발표 when:2d"))),
] + [(name, (lambda u: (lambda: fetch_rss(u)))(url)) for name, url in KR_OFFICIAL_FEEDS]

# ---------------- 브리핑 생성 ----------------

def build_briefing(results, errors):
    now = datetime.now(KST)
    L = []
    L.append("# 환경 브리핑 — 정보기관 v0.2a-p1")
    L.append(f"- 생성 시각: {now.strftime('%Y-%m-%d %H:%M')} KST")
    L.append("- 커버리지(규칙 8): 아래 원천의 최근 게시물만 담음. **여기 없는 정책·공시는 존재할 수 있다(그물은 표본).** 구글뉴스 경유 항목은 정책 원문이 아니라 언론 보도임.")
    L.append("")
    if errors:
        L.append("## ⚠️ 수집 실패 경고 — 수동 확인 요망")
        for name, msg in errors:
            L.append(f"- **{name}**: {msg}")
        L.append("")
    for name, items in results:
        L.append(f"## {name} (최신 {len(items)}건)")
        for it in items:
            tag = f" `[{' · '.join(it['sectors'])}]`" if it["sectors"] else ""
            org = f" ({it['org']})" if it["org"] else ""
            L.append(f"- {it['date']} |{org} [{it['title']}]({it['link']}){tag}")
        L.append("")
    counts = {}
    for _, items in results:
        for it in items:
            for s in it["sectors"]:
                counts[s] = counts.get(s, 0) + 1
    if counts:
        L.append("## 섹터 태그 요약")
        L.append(" · ".join(f"{s} {n}건" for s, n in sorted(counts.items(), key=lambda x: -x[1])))
        L.append("")
    L.append("---")
    L.append("_다음 단계: 이 파일의 Raw 링크를 Claude에게 붙여넣으면 분석 보고를 받는다._")
    return "\n".join(L)

def main():
    results, errors = [], []
    for name, fn in SOURCES:
        try:
            items = fn()
            results.append((name, items))
            print(f"[OK] {name}: {len(items)}건")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:150]}"
            errors.append((name, msg))
            print(f"[FAIL] {name}: {msg}")
    os.makedirs("briefing", exist_ok=True)
    with open("briefing/env_latest.md", "w", encoding="utf-8") as f:
        f.write(build_briefing(results, errors))
    print(f"브리핑 생성: 성공 {len(results)} / 실패 {len(errors)}")

if __name__ == "__main__":
    main()
