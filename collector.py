# -*- coding: utf-8 -*-
"""
등대 collector v0.5 — 수집 전용 (본문·초록 + 한국어 번역)
- 정책·뉴스 원천에서 항목을 모아 원자료(JSON)로 저장한다. 요약·보고는 하지 않는다.
- 산출물: data/raw_YYYY-MM-DD.json (당일 원자료), data/latest.json (최신 사본)
- 실패는 침묵이 아니라 소음으로: 원천별 성패를 기록한다.
"""
import os, re, json
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

try:
    import feedparser
    HAS_FEEDPARSER = True
except ImportError:
    HAS_FEEDPARSER = False

KST = timezone(timedelta(hours=9))
UA = "LighthouseIntel/0.4 (personal research bot)"
MAX_PER_SECTION = 15

SECTOR_KEYWORDS = {
    "반도체/AI": ["semiconductor", "chip", "ai", "artificial intelligence", "data center",
                "반도체", "인공지능", "파운드리", "hbm", "데이터센터"],
    "전력/원자력": ["electric grid", "power plant", "nuclear", "grid",
                 "전력", "송전", "변전", "원전", "smr", "에너지"],
    "냉각/냉매": ["refrigerant", "cooling", "hfc", "냉매", "냉각", "액침"],
    "수출통제/관세": ["export control", "tariff", "sanction", "수출통제", "관세", "제재", "무역", "232조"],
    "금리/통화": ["interest rate", "federal reserve", "monetary",
                "금리", "기준금리", "통화정책", "한국은행", "환율"],
    "보조금/세제": ["subsidy", "tax credit", "grant", "보조금", "세액공제", "지원금", "세제"],
    "바이오/의료": ["fda", "drug", "clinical", "바이오", "의약", "임상", "제약"],
    "방산/우주": ["defense", "military", "space", "방위", "방산", "우주"],
    "2차전지/ESS": ["battery", "energy storage", "ess", "이차전지", "배터리", "양극재"],
    "모빌리티": ["vehicle", "automotive", "자동차", "전기차", "자율주행"],
    "조선/해운": ["shipbuilding", "shipyard", "vessel", "조선업", "해운", "선박", "컨테이너선", "수주"],
    "항공/물류": ["airline", "aviation", "cargo", "logistics", "항공", "물류", "운송"],
    "원유/가스": ["oil", "crude", "petroleum", "lng", "정유", "원유", "천연가스", "석유"],
    "금속/광물": ["copper", "gold", "nickel", "lithium", "rare earth",
               "구리", "금값", "니켈", "철광석", "희토류", "광물", "제련", "폴리실리콘"],
    "건설/부동산": ["construction", "housing", "real estate", "건설", "부동산", "분양", "재건축", "주택"],
    "금융/증권": ["금융위", "금감원", "증권", "은행", "보험", "가상자산", "펀드"],
}

MEDIA_TAIL = re.compile(r"\s*[-–—]\s*[^-–—]{1,25}$")

def strip_media(title):
    """제목 끝의 언론사 꼬리를 반복 제거 (조선비즈 - Chosunbiz 처럼 두 번 붙는 경우 대응)"""
    t = title or ""
    for _ in range(3):
        t2 = MEDIA_TAIL.sub("", t).strip()
        if t2 == t or len(t2) < 8:
            break
        t = t2
    return t

def _compile():
    out = {}
    for sec, kws in SECTOR_KEYWORDS.items():
        pats = []
        for k in kws:
            k = k.strip().lower()
            if re.fullmatch(r"[a-z0-9 ]+", k):
                pats.append(re.compile(r"\b" + re.escape(k) + r"\b"))
            else:
                pats.append(re.compile(re.escape(k)))
        out[sec] = pats
    return out

_PATTERNS = _compile()

def tag_sectors(text):
    t = (text or "").lower()
    return [s for s, pats in _PATTERNS.items() if any(p.search(t) for p in pats)]

def load_watchlist():
    try:
        return [s.strip() for s in open("watchlist.txt", encoding="utf-8")
                if s.strip() and not s.strip().startswith("#")]
    except FileNotFoundError:
        return []

_WL = None

def watch_hit(core_title):
    """언론사 꼬리를 뗀 제목에서만 감시어를 찾는다"""
    global _WL
    if _WL is None:
        _WL = []
        for t in load_watchlist():
            tl = t.strip().lower()
            if re.fullmatch(r"[a-z0-9 .\-]+", tl):
                _WL.append((t, re.compile(r"\b" + re.escape(tl) + r"\b")))
            else:
                _WL.append((t, re.compile(re.escape(tl))))
    low = (core_title or "").lower()
    return [t for t, p in _WL if p.search(low)]

# ---------------- 번역 (무료, 실패 시 원문 유지) ----------------
GLOSS = {
    "Department of Commerce": "상무부", "Commerce Department": "상무부",
    "International Trade Administration": "국제무역청",
    "Department of Energy": "에너지부", "Energy Department": "에너지부",
    "Department of the Treasury": "재무부", "Treasury Department": "재무부",
    "Department of Health and Human Services": "보건복지부",
    "Health and Human Services Department": "보건복지부",
    "National Institutes of Health": "국립보건원",
    "Environmental Protection Agency": "환경보호청",
    "Securities and Exchange Commission": "증권거래위원회",
    "Federal Reserve": "연방준비제도", "Federal Communications Commission": "연방통신위원회",
    "Nuclear Regulatory Commission": "원자력규제위원회",
    "Food and Drug Administration": "식품의약국",
    "Department of Defense": "국방부", "Department of Transportation": "교통부",
    "Small Business Administration": "중소기업청",
    "Fish and Wildlife Service": "어류야생동물국",
    "Antidumping Duty": "반덤핑 관세", "Countervailing Duty": "상계관세",
    "Administrative Review": "행정재심", "Final Results": "최종 결과",
    "Notice of Proposed Rulemaking": "규칙제정 예고", "Proposed Rule": "규칙안",
    "Final Rule": "최종 규칙", "Request for Comment": "의견 요청",
    "Information Collection": "정보 수집", "Duty-Free Entry": "면세 반입",
    "Patent License": "특허 라이선스", "Available for License": "라이선스 제공",
    "Tariff": "관세", "Export Control": "수출통제", "Sanctions": "제재",
    "People's Republic of China": "중국", "United States": "미국",
}

_tr_cache = {}
_tr_dead = {"v": False}

def translate(text, target="ko"):
    """무료 번역 시도. 실패하면 None (원문 유지)."""
    if not text or _tr_dead["v"]:
        return None
    if re.fullmatch(r"[^A-Za-z]*", text):     # 영문이 없으면 번역 불필요
        return None
    key = text[:400]
    if key in _tr_cache:
        return _tr_cache[key]
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
                         params={"client": "gtx", "sl": "en", "tl": target, "dt": "t", "q": key},
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            data = r.json()
            out = "".join(seg[0] for seg in data[0] if seg and seg[0])
            _tr_cache[key] = out
            return out
    except Exception:
        pass
    _tr_dead["v"] = True      # 한 번 막히면 이후 시도하지 않음
    return None

def glossary(text):
    t = text or ""
    for en, ko in GLOSS.items():
        t = re.sub(re.escape(en), ko, t, flags=re.I)
    return t

def to_korean(text):
    """번역 → 실패 시 용어사전만 적용"""
    if not text:
        return text, False
    tr = translate(text)
    if tr:
        return glossary(tr), True
    g = glossary(text)
    return g, False

# ---------------- 본문·초록 ----------------
def fetch_body(url, limit=600):
    """기사·문서 본문 앞부분을 가져온다. 실패하면 None."""
    try:
        r = requests.get(url, headers={"User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"},
            timeout=12, allow_redirects=True)
        if r.status_code != 200 or len(r.text) < 500:
            return None
        html = r.text
        html = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html)
        # 본문 후보: <p> 태그들
        ps = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
        txt = " ".join(re.sub(r"(?s)<[^>]+>", "", p) for p in ps)
        txt = re.sub(r"&[a-z]+;|&#\d+;", " ", txt)
        txt = re.sub(r"\s+", " ", txt).strip()
        if len(txt) < 80:
            m = re.search(r'(?is)<meta[^>]+(?:name="description"|property="og:description")[^>]+content="([^"]{60,})"', html)
            txt = m.group(1).strip() if m else ""
        return txt[:limit] if len(txt) >= 60 else None
    except Exception:
        return None

# ---------------- 원천 ----------------

def fetch_federal_register():
    r = requests.get("https://www.federalregister.gov/api/v1/documents.json",
                     params={"per_page": MAX_PER_SECTION, "order": "newest"},
                     headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    items = []
    for d in r.json().get("results", []):
        title = (d.get("title") or "").strip()
        abst = (d.get("abstract") or "")[:700]
        ko_t, ok_t = to_korean(title)
        ko_a, _ = to_korean(abst) if abst else ("", False)
        org_en = ", ".join(a.get("name", "") for a in (d.get("agencies") or [])[:2])
        items.append({"title": title, "core": ko_t or title, "title_en": title,
                      "date": d.get("publication_date", ""),
                      "org": glossary(org_en), "link": d.get("html_url", ""),
                      "abstract": ko_a or abst, "abstract_en": abst,
                      "translated": ok_t, "official": True,
                      "kind": d.get("type", ""), "docket": d.get("docket_id", "")})
    if not items:
        raise RuntimeError("응답은 왔으나 문서 0건 — API 형식 변경 의심")
    return items

def fetch_rss(url, official=False):
    if not HAS_FEEDPARSER:
        raise RuntimeError("feedparser 미설치")
    f = feedparser.parse(url, agent=UA)
    if not f.entries:
        raise RuntimeError(f"피드 비었음/오류: {str(getattr(f,'bozo_exception','항목 0건'))[:120]}")
    items = []
    for e in f.entries[:MAX_PER_SECTION]:
        title = getattr(e, "title", "").strip()
        link = getattr(e, "link", "")
        summ = re.sub(r"<[^>]+>", "", getattr(e, "summary", "")).strip()
        summ = re.sub(r"\s+", " ", summ)[:500]
        body = None
        if len(summ) < 120 and link:
            body = fetch_body(link)
        items.append({"title": title, "core": strip_media(title),
                      "date": getattr(e, "published", getattr(e, "updated", ""))[:16],
                      "org": getattr(e, "source", {}).get("title", "") if hasattr(e, "source") else "",
                      "link": link, "abstract": (body or summ or "")[:600],
                      "body_ok": bool(body), "official": official})
    return items

def gnews(query):
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"

KR_OFFICIAL_FEEDS = [
    ("정책브리핑 보도자료(공식)", "https://www.korea.kr/rss/dept_press.xml"),
    ("정책브리핑 정책뉴스(공식)", "https://www.korea.kr/rss/policy.xml"),
]

SOURCES = [
    ("US_FEDREG", "미국 연방관보(공식)", fetch_federal_register),
    ("KR_ECON", "한국 경제부처·한은", lambda: fetch_rss(gnews("기획재정부 OR 산업통상자원부 OR 금융위원회 OR 한국은행 when:2d"))),
    ("KR_REG", "한국 규제·수출통제", lambda: fetch_rss(gnews("규제 OR 수출통제 OR 관세 발표 when:2d"))),
] + [(f"KR_OFF{i}", n, (lambda u: (lambda: fetch_rss(u, official=True)))(u))
     for i, (n, u) in enumerate(KR_OFFICIAL_FEEDS)]


def main():
    import time as _t
    now = datetime.now(KST)
    sources, errors, items = [], [], []
    seq = 0
    for sid, name, fn in SOURCES:
        try:
            got = fn()
            for it in got:
                seq += 1
                _t.sleep(0.05)
                core = it.get("core") or it["title"]
                it.update(id=seq, src=sid, src_name=name,
                          sectors=tag_sectors(core + " " + it.get("abstract", "")),
                          watch=watch_hit(core))
                items.append(it)
            sources.append({"id": sid, "name": name, "count": len(got), "ok": True})
            print(f"[OK] {name}: {len(got)}건")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:150]}"
            errors.append({"id": sid, "name": name, "error": msg})
            sources.append({"id": sid, "name": name, "count": 0, "ok": False, "error": msg})
            print(f"[FAIL] {name}: {msg}")

    data = {
        "generated": now.strftime("%Y-%m-%d %H:%M"),
        "date": now.strftime("%Y-%m-%d"),
        "sources": sources,
        "errors": errors,
        "watchlist": load_watchlist(),
        "items": items,
        "coverage": "위 원천의 최근 게시물만 담음. 여기 없는 정책·공시는 존재할 수 있음(그물은 표본).",
    }
    os.makedirs("data", exist_ok=True)
    for path in (f"data/raw_{data['date']}.json", "data/latest.json"):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"수집 완료: {len(items)}건 · 성공 {len(sources)-len(errors)}/{len(sources)} 원천 → data/latest.json")


if __name__ == "__main__":
    main()
