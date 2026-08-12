# -*- coding: utf-8 -*-
"""
등대 collector v1.0 — 수집 전용 (투자 판단 재료만)
원천: DART(국내 공시) · EDGAR(미국 공시) · 연방관보(미국 정책) · 정책브리핑(한국 정책)
      · 정책/산업 언론 · 해외발 충격(영문) · 예정 일정
철칙: 개별 기업 정보는 언론이 아니라 공시 원문에서. 조회 전용, 매매 기능 없음.
"""
import os, re, io, json, time, zipfile
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests

try:
    import feedparser
    HAS_FEED = True
except ImportError:
    HAS_FEED = False

KST = timezone(timedelta(hours=9))
UA = "LighthouseIntel/1.0 (personal research bot)"
SEC_UA = "Pado Research Tool (personal use; contact: pado-research@proton.me)"
TODAY = datetime.now(KST)

# ══════════════ 분류 ══════════════
SECTORS = {
    "반도체/AI": ["semiconductor","chip","artificial intelligence","data center","반도체","인공지능","파운드리","hbm","데이터센터","gpu"],
    "전력/원자력": ["electric grid","power plant","nuclear","전력","송전","변전","원전","smr","에너지","발전소"],
    "냉각/냉매": ["refrigerant","cooling","hfc","냉매","냉각","액침"],
    "수출통제/관세": ["export control","tariff","sanction","수출통제","관세","제재","무역","232조","반덤핑","상계관세"],
    "금리/통화": ["interest rate","federal reserve","monetary","금리","기준금리","통화정책","금통위","fomc","환율"],
    "보조금/세제": ["subsidy","tax credit","grant","보조금","세액공제","지원금","세제","조세특례"],
    "바이오/의료": ["fda","clinical trial","바이오","의약","임상","제약","의료기기"],
    "방산/우주": ["defense","military","space","방위","방산","우주","항공우주"],
    "2차전지/ESS": ["battery","energy storage","이차전지","배터리","양극재","ess"],
    "모빌리티": ["vehicle","automotive","자동차","전기차","자율주행"],
    "조선/해운": ["shipbuilding","shipyard","조선업","해운","선박","컨테이너선","운임"],
    "항공/물류": ["airline","aviation","logistics","항공","물류","운송"],
    "원유/가스": ["crude oil","petroleum","lng","정유","원유","천연가스","석유"],
    "금속/광물": ["copper","rare earth","critical mineral","구리","니켈","철강","희토류","광물","제련","폴리실리콘"],
    "건설/부동산": ["construction","housing","건설","부동산","분양","재건축","주택공급","soc"],
    "금융/증권": ["금융위","금감원","증권","가상자산","자본시장","공매도"],
}

# ══════════════ 유형 (투자 의미) ══════════════
KIND = {
    "의지": ["공급계약","수주","시설투자","자기주식","자사주","취득 결정","투자 결정","증설","신규시설"],
    "실체": ["잠정실적","영업실적","분기보고서","반기보고서","사업보고서","매출액또는손익구조"],
    "자본": ["유상증자","무상증자","전환사채","신주인수권","감자","교환사채"],
    "위험": ["소송","횡령","배임","관리종목","거래정지","감사의견","상장폐지","손실발생","최대주주변경","불성실공시"],
    "지분": ["주식등의대량보유","임원ㆍ주요주주","의결권"],
    "일정": ["실적발표","주주총회","공시예고","기업설명회"],
}
def kind_of(t):
    t = t or ""
    return [k for k, ws in KIND.items() if any(w in t for w in ws)]

# 개별 기업 주가·잡담 기사 제외
NOISE = re.compile(r"(경시대회|수상|시상|캠페인|봉사|기념식|위촉|임명식|채용|사내|동호회|"
                   r"주가|급등|급락|상한가|하한가|추천주|유망주|테마주|목표주가|증권가|호재|악재|"
                   r"운세|날씨|스포츠|연예)")

MEDIA_TAIL = re.compile(r"\s*[-–—]\s*[^-–—]{1,25}$")
def strip_media(t):
    t = t or ""
    for _ in range(3):
        n = MEDIA_TAIL.sub("", t).strip()
        if n == t or len(n) < 8: break
        t = n
    return t

def _pat(kws):
    out = []
    for k in kws:
        k = k.strip().lower()
        out.append(re.compile(r"\b"+re.escape(k)+r"\b" if re.fullmatch(r"[a-z0-9 ]+", k) else re.escape(k)))
    return out
_SEC = {s: _pat(k) for s, k in SECTORS.items()}
def tag_sectors(t):
    t = (t or "").lower()
    return [s for s, ps in _SEC.items() if any(p.search(t) for p in ps)]

def load_watchlist():
    try:
        return [s.strip() for s in open("watchlist.txt", encoding="utf-8")
                if s.strip() and not s.strip().startswith("#")]
    except FileNotFoundError:
        return []

def load_symbols():
    """watchlist.txt 에서 종목코드/티커만 추출 (6자리 숫자 = 국내, 대문자 = 미국)"""
    kr, us = [], []
    for w in load_watchlist():
        w = w.strip()
        if re.fullmatch(r"\d{6}", w): kr.append(w)
        elif re.fullmatch(r"[A-Z]{1,5}", w): us.append(w)
    return kr, us

_WL = None
def watch_hit(t):
    global _WL
    if _WL is None:
        _WL = [(w, re.compile(re.escape(w.lower()))) for w in load_watchlist()]
    low = (t or "").lower()
    return [w for w, p in _WL if p.search(low)]

# ══════════════ 번역 ══════════════
GLOSS = {"Department of Commerce":"상무부","Commerce Department":"상무부","International Trade Administration":"국제무역청",
 "Department of Energy":"에너지부","Energy Department":"에너지부","Department of the Treasury":"재무부",
 "Treasury Department":"재무부","Health and Human Services Department":"보건복지부","National Institutes of Health":"국립보건원",
 "Environmental Protection Agency":"환경보호청","Securities and Exchange Commission":"증권거래위원회",
 "Federal Reserve":"연준","Nuclear Regulatory Commission":"원자력규제위원회","Food and Drug Administration":"식품의약국",
 "Department of Defense":"국방부","Small Business Administration":"중소기업청","Bureau of Industry and Security":"산업안보국",
 "Antidumping Duty":"반덤핑 관세","Countervailing Duty":"상계관세","Administrative Review":"행정재심",
 "Final Results":"최종 결과","Proposed Rule":"규칙안","Final Rule":"최종 규칙","Notice of Proposed Rulemaking":"규칙제정 예고",
 "Export Control":"수출통제","Entity List":"수출통제 명단","Tariff":"관세","People's Republic of China":"중국","United States":"미국"}
_tr, _dead = {}, {"v": False}
def translate(t):
    if not t or _dead["v"] or not re.search(r"[A-Za-z]{4}", t): return None
    k = t[:400]
    if k in _tr: return _tr[k]
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single",
            params={"client":"gtx","sl":"en","tl":"ko","dt":"t","q":k},
            headers={"User-Agent":"Mozilla/5.0"}, timeout=15)
        if r.status_code == 200:
            out = "".join(s[0] for s in r.json()[0] if s and s[0])
            _tr[k] = out; return out
    except Exception: pass
    _dead["v"] = True
    return None
def gloss(t):
    for en, ko in GLOSS.items():
        t = re.sub(re.escape(en), ko, t or "", flags=re.I)
    return t
def to_ko(t):
    tr = translate(t)
    return (gloss(tr), True) if tr else (gloss(t), False)

def item(**kw):
    kw.setdefault("official", False); kw.setdefault("abstract", "")
    kw.setdefault("kinds", []); kw.setdefault("date", "")
    core = kw.get("core") or kw.get("title", "")
    kw["sectors"] = tag_sectors(core + " " + (kw.get("abstract") or ""))
    kw["watch"] = watch_hit(core)
    return kw

# ══════════════ 1. DART 국내 공시 ══════════════
def dart_key():
    try:
        for l in open("key.txt", encoding="utf-8"):
            if "=" in l and l.split("=",1)[0].strip().upper() in ("DART_KEY","DART_API_KEY"):
                return l.split("=",1)[1].strip()
    except Exception: pass
    return os.environ.get("DART_KEY", "")

def dart_corp():
    key = dart_key()
    cf = "dart_corp.json"
    if os.path.exists(cf):
        try: return json.load(open(cf, encoding="utf-8"))
        except Exception: pass
    r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                     params={"crtfc_key": key}, timeout=60)
    m = {}
    if r.status_code == 200:
        try:
            z = zipfile.ZipFile(io.BytesIO(r.content))
            xml = z.read(z.namelist()[0]).decode("utf-8", errors="ignore")
            for b in re.findall(r"<list>(.*?)</list>", xml, re.S):
                sc = re.search(r"<stock_code>(.*?)</stock_code>", b)
                cc = re.search(r"<corp_code>(.*?)</corp_code>", b)
                nm = re.search(r"<corp_name>(.*?)</corp_name>", b)
                if sc and sc.group(1).strip() and cc:
                    m[sc.group(1).strip()] = {"code": cc.group(1).strip(),
                                              "name": nm.group(1).strip() if nm else ""}
            json.dump(m, open(cf,"w",encoding="utf-8"), ensure_ascii=False)
        except Exception: pass
    return m

def fetch_dart():
    """전 시장 주요 공시 + 워치리스트 종목 공시"""
    key = dart_key()
    if not key: raise RuntimeError("key.txt 에 DART_KEY 없음")
    out = []
    bgn = (TODAY - timedelta(days=3)).strftime("%Y%m%d")
    end = TODAY.strftime("%Y%m%d")
    corp = dart_corp()
    rev = {v["code"]: (k, v["name"]) for k, v in corp.items()}
    # 전 시장 (유가/코스닥 주요공시)
    for mkt, label in (("Y","유가증권"), ("K","코스닥")):
        for page in (1, 2):
            r = requests.get("https://opendart.fss.or.kr/api/list.json",
                params={"crtfc_key":key,"bgn_de":bgn,"end_de":end,"corp_cls":mkt,
                        "page_count":100,"page_no":page,"pblntf_ty":"B"}, timeout=40)
            j = r.json() if r.status_code == 200 else {}
            if j.get("status") != "000": break
            for x in j.get("list", []):
                nm = x.get("report_nm","")
                ks = kind_of(nm)
                if not ks: continue
                sc = rev.get(x.get("corp_code"), ("", x.get("corp_name","")))
                out.append(item(title=f"{x.get('corp_name')} — {nm}", core=f"{x.get('corp_name')} {nm}",
                    date=x.get("rcept_dt",""), org=f"DART·{label}", official=True, kinds=ks,
                    link=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}",
                    symbol=sc[0], company=x.get("corp_name",""), src_kind="공시"))
            time.sleep(0.15)
    # 워치리스트 종목: 유형 무관 전수
    kr, _ = load_symbols()
    for s in kr[:20]:
        c = corp.get(s)
        if not c: continue
        r = requests.get("https://opendart.fss.or.kr/api/list.json",
            params={"crtfc_key":key,"corp_code":c["code"],"bgn_de":bgn,"end_de":end,
                    "page_count":30,"page_no":1}, timeout=40)
        j = r.json() if r.status_code == 200 else {}
        for x in j.get("list", []):
            out.append(item(title=f"⭐ {c['name']} — {x.get('report_nm')}",
                core=f"{c['name']} {x.get('report_nm')}", date=x.get("rcept_dt",""),
                org="DART·감시종목", official=True, kinds=kind_of(x.get("report_nm","")) or ["일정"],
                link=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={x.get('rcept_no')}",
                symbol=s, company=c["name"], src_kind="공시"))
        time.sleep(0.15)
    if not out: raise RuntimeError("공시 0건 (조회 기간에 해당 유형 없음일 수 있음)")
    return out

# ══════════════ 2. EDGAR 미국 공시 ══════════════
US_FORM = {"8-K":"수시공시(중대사건)","10-Q":"분기보고서","10-K":"연간보고서","4":"내부자 매매",
           "SC 13D":"5%↑ 대주주(경영참여)","SC 13G":"5%↑ 대주주","S-4":"합병용 주식등록","425":"합병 공시"}
def fetch_edgar():
    _, us = load_symbols()
    if not us: raise RuntimeError("watchlist.txt 에 미국 티커 없음 (예: SOUN)")
    tick = {}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json",
                         headers={"User-Agent": SEC_UA}, timeout=30)
        d = r.json()
        for x in (list(d.values()) if isinstance(d, dict) else d):
            tick[str(x.get("ticker","")).upper()] = (str(x["cik_str"]).zfill(10), x.get("title",""))
    except Exception as e:
        raise RuntimeError(f"티커 목록 실패: {type(e).__name__}")
    out = []
    for t in us[:12]:
        info = tick.get(t)
        if not info: continue
        cik, name = info
        try:
            r = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                             headers={"User-Agent": SEC_UA}, timeout=30)
            rec = (r.json().get("filings") or {}).get("recent") or {}
            forms = rec.get("form", [])
            for i in range(min(len(forms), 40)):
                d = rec["filingDate"][i]
                if (TODAY.date() - datetime.fromisoformat(d).date()).days > 5: break
                f = forms[i]
                lab = US_FORM.get(f, US_FORM.get(f.split("/")[0], f))
                acc = rec["accessionNumber"][i].replace("-","")
                out.append(item(title=f"⭐ {name} — {f} {lab}", core=f"{name} {f} {lab}",
                    date=d, org="SEC·감시종목", official=True,
                    kinds=(["위험"] if f.startswith("8-K") else
                           ["실체"] if f.startswith(("10-Q","10-K")) else
                           ["지분"] if f.startswith(("SC 13","4")) else ["자본"]),
                    link=f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{rec.get('primaryDocument',[''])[i]}",
                    symbol=t, company=name, src_kind="공시"))
        except Exception: pass
        time.sleep(0.2)
    if not out: raise RuntimeError("최근 5일 내 감시종목 공시 없음")
    return out

# ══════════════ 3. 미국 정책 (연방관보) ══════════════
POL_KEY = ["tariff","export control","semiconductor","critical mineral","energy","nuclear",
           "battery","vehicle","drug","medical device","shipbuilding","steel","aluminum",
           "solar","polysilicon","artificial intelligence","data center","sanction","entity list"]
def fetch_fedreg():
    r = requests.get("https://www.federalregister.gov/api/v1/documents.json",
        params={"per_page":40,"order":"newest",
                "conditions[type][]":["RULE","PRORULE","PRESDOCU"]},
        headers={"User-Agent":UA}, timeout=30)
    r.raise_for_status()
    out = []
    for d in r.json().get("results", []):
        title = (d.get("title") or "").strip()
        abst = (d.get("abstract") or "")[:800]
        blob = (title + " " + abst).lower()
        if not any(k in blob for k in POL_KEY): continue
        kt, ok = to_ko(title)
        ka, _ = to_ko(abst) if abst else ("", False)
        out.append(item(title=title, core=kt or title, title_en=title,
            date=d.get("publication_date",""), abstract=ka or abst, abstract_en=abst,
            org=gloss(", ".join(a.get("name","") for a in (d.get("agencies") or [])[:2])),
            link=d.get("html_url",""), official=True, translated=ok,
            kinds=["정책"], src_kind="정책",
            effective=d.get("effective_on") or ""))
    if not out: raise RuntimeError("투자 관련 정책 문서 0건")
    return out

# ══════════════ 4. 한국 정책 원문 ══════════════
def fetch_rss(url, official=False, src_kind="정책", limit=20):
    if not HAS_FEED: raise RuntimeError("feedparser 미설치")
    f = feedparser.parse(url, agent=UA)
    if not f.entries: raise RuntimeError(f"피드 비었음: {str(getattr(f,'bozo_exception','0건'))[:100]}")
    out = []
    for e in f.entries[:limit]:
        t = getattr(e, "title", "").strip()
        core = strip_media(t)
        if NOISE.search(core): continue
        summ = re.sub(r"\s+"," ", re.sub(r"<[^>]+>","", getattr(e,"summary",""))).strip()[:600]
        out.append(item(title=t, core=core, date=getattr(e,"published",getattr(e,"updated",""))[:16],
            abstract=summ, link=getattr(e,"link",""), official=official,
            org=getattr(getattr(e,"source",None),"title","") if hasattr(e,"source") else "",
            kinds=["정책"], src_kind=src_kind))
    if not out: raise RuntimeError("필터 통과 항목 0건")
    return out

def gnews(q, days=2):
    return f"https://news.google.com/rss/search?q={quote(q+f' when:{days}d')}&hl=ko&gl=KR&ceid=KR:ko"
def gnews_en(q, days=2):
    return f"https://news.google.com/rss/search?q={quote(q+f' when:{days}d')}&hl=en-US&gl=US&ceid=US:en"

# ══════════════ 5. 예정 일정 ══════════════
def fetch_calendar():
    """예정된 사건 — 재료에서 시행일·발표일을 뽑아 모은다"""
    out = []
    # 연준 FOMC (공개 일정)
    try:
        r = requests.get("https://www.federalreserve.gov/json/ne-fomc.json",
                         headers={"User-Agent":UA}, timeout=20)
        if r.status_code == 200:
            for x in (r.json() or [])[:12]:
                d = str(x.get("d",""))[:10]
                if d and d >= TODAY.strftime("%Y-%m-%d"):
                    out.append(item(title=f"[예정] FOMC {d}", core=f"FOMC 회의 {d}", date=d,
                        org="연준", official=True, kinds=["일정"], src_kind="일정",
                        link="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        abstract="미국 기준금리 결정 회의. 전후로 시장 변동성이 커질 수 있습니다."))
    except Exception: pass
    if not out: raise RuntimeError("일정 원천 응답 없음")
    return out

# ══════════════ 원천 목록 ══════════════
SOURCES = [
    ("DART",     "국내 공시 (DART 원문)",        fetch_dart),
    ("EDGAR",    "미국 공시 (SEC 원문)",         fetch_edgar),
    ("FEDREG",   "미국 정책 (연방관보 원문)",     fetch_fedreg),
    ("KR_POLICY","한국 정책 (부처 발표)",        lambda: fetch_rss(gnews(
        "정부 대책 OR 입법예고 OR 시행령 OR 지원방안 OR 육성전략 OR 규제완화 OR 세제개편"), src_kind="정책")),
    ("KR_INDUS", "한국 산업·공급망",             lambda: fetch_rss(gnews(
        "수출 규제 OR 공급망 OR 산업 육성 OR 발주 OR 증설 투자 OR 전력수급"), src_kind="산업")),
    ("GLOBAL",   "해외발 충격 (영문)",           lambda: fetch_rss(gnews_en(
        "China export restriction OR EU regulation chips OR supply chain disruption OR critical minerals"),
        src_kind="해외")),
    ("CALENDAR", "예정 일정",                    fetch_calendar),
]

def main():
    sources, errors, items, seq = [], [], [], 0
    for sid, name, fn in SOURCES:
        try:
            got = fn()
            for it in got:
                seq += 1
                it.update(id=seq, src=sid, src_name=name)
                items.append(it)
            sources.append({"id":sid,"name":name,"count":len(got),"ok":True})
            print(f"[OK] {name}: {len(got)}건")
        except Exception as e:
            msg = f"{type(e).__name__}: {str(e)[:150]}"
            errors.append({"id":sid,"name":name,"error":msg})
            sources.append({"id":sid,"name":name,"count":0,"ok":False,"error":msg})
            print(f"[FAIL] {name}: {msg}")
    data = {"generated": TODAY.strftime("%Y-%m-%d %H:%M"), "date": TODAY.strftime("%Y-%m-%d"),
            "sources": sources, "errors": errors, "watchlist": load_watchlist(), "items": items,
            "coverage": "공시·정책 원문 우선. 개별 기업 주가·잡담 기사는 제외. 여기 없는 정보는 존재할 수 있음."}
    os.makedirs("data", exist_ok=True)
    for p in (f"data/raw_{data['date']}.json", "data/latest.json"):
        json.dump(data, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"수집 완료: {len(items)}건 · 원천 {len(sources)-len(errors)}/{len(sources)}")

if __name__ == "__main__":
    main()
