# -*- coding: utf-8 -*-
"""
정보기관 v0.2a — 최소 생존 버전
미국 연방관보 + 한국 정책브리핑을 수집해 일일 환경 브리핑(briefing/env_latest.md)을 만든다.
설계 원칙: 실패는 침묵이 아니라 소음으로 — 원천이 죽으면 브리핑 맨 위에 경고를 박는다.
"""
import os, traceback
from datetime import datetime, timezone, timedelta

import requests

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

KST = timezone(timedelta(hours=9))
UA = "JangbuIntel/0.2a (personal research bot)"
MAX_PER_SECTION = 12

SECTOR_KEYWORDS = {
    "반도체/AI": ["semiconductor", "chip", " ai ", "artificial intelligence", "반도체", "인공지능", "파운드리", "hbm", "데이터센터", "data center"],
    "전력/원자력": ["electric grid", "power plant", "nuclear", "전력", "송전", "변전", "원전", "smr", "에너지"],
    "냉각/냉매": ["refrigerant", "cooling", "hfc", "냉매", "냉각", "액침"],
    "수출통제/관세": ["export control", "tariff", "sanction", "수출통제", "관세", "제재", "무역"],
    "금리/통화": ["interest rate", "federal reserve", "monetary", "금리", "기준금리", "통화정책", "한국은행"],
    "보조금/세제": ["subsidy", "tax credit", "grant", "보조금", "세액공제", "지원금", "세제"],
    "바이오/의료": ["fda", "drug", "clinical", "바이오", "의약", "임상", "제약"],
    "방산/우주": ["defense", "military", "space", "방위", "방산", "우주"],
    "2차전지/ESS": ["battery", "energy storage", "이차전지", "배터리", "양극재", "ess"],
    "모빌리티": ["vehicle", "automotive", "자동차", "전기차", "자율주행"],
}

def tag_sectors(text):
    t = " " + (text or "").lower() + " "
    return [s for s, kws in SECTOR_KEYWORDS.items() if any(k in t for k in kws)]

# ---------------- 원천들 ----------------

def fetch_federal_register():
    """미국 연방관보 — 공식 API, 키 불필요"""
    r = requests.get(
        "https://www.federalregister.gov/api/v1/documents.json",
        params={"per_page": MAX_PER_SECTION, "order": "newest"},
        headers={"User-Agent": UA}, timeout=30,
    )
    r.raise_for_status()
    items = []
    for d in r.json().get("results", []):
        title = d.get("title", "") or ""
        abstract = d.get("abstract") or ""
        items.append({
            "title": title.strip(),
            "date": d.get("publication_date", ""),
            "org": ", ".join(a.get("name", "") for a in (d.get("agencies") or [])[:2]),
            "link": d.get("html_url", ""),
            "sectors": tag_sectors(title + " " + abstract),
        })
    if not items:
        raise RuntimeError("응답은 왔으나 문서 0건 — API 형식 변경 의심")
    return items

def fetch_rss(url):
    """RSS 공통 수집기"""
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

SOURCES = [
    ("🇺🇸 연방관보(Federal Register)", fetch_federal_register),
    ("🇰🇷 정책브리핑·정책뉴스", lambda: fetch_rss("https://www.korea.kr/rss/policy.xml")),
    ("🇰🇷 정책브리핑·보도자료", lambda: fetch_rss("https://www.korea.kr/rss/pressrelease.xml")),
]

# ---------------- 브리핑 생성 ----------------

def build_briefing(results, errors):
    now = datetime.now(KST)
    L = []
    L.append("# 환경 브리핑 — 정보기관 v0.2a")
    L.append(f"- 생성 시각: {now.strftime('%Y-%m-%d %H:%M')} KST")
    L.append("- 커버리지(규칙 8): 아래 명시된 원천의 최근 게시물만 담음. **여기 없는 정책·공시는 존재할 수 있다(그물은 표본이지 전수가 아님).**")
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
    # 섹터 요약
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
    print(f"브리핑 생성 완료: 성공 {len(results)} / 실패 {len(errors)}")

if __name__ == "__main__":
    main()
