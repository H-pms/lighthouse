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
    "실체": ["잠정","영업실적","실적","분기보고서","반기보고서","사업보고서","매출액또는손익구조","공정공시"],
    "자본": ["유상증자","무상증자","전환사채","신주인수권","감자","교환사채"],
    "위험": ["소송","횡령","배임","관리종목","거래정지","감사의견","상장폐지","손실발생","최대주주변경","불성실공시"],
    "지분": ["주식등의대량보유","임원ㆍ주요주주","의결권"],
    "일정": ["실적발표","주주총회","공시예고","기업설명회"],
}
def kind_of(t):
    t = t or ""
    return [k for k, ws in KIND.items() if any(w in t for w in ws)]

# 개별 기업 주가·잡담 기사 제외
NOISE = re.compile(r"(경시대회|수상|시상|캠페인|봉사|기념식|위촉|임명식|채용|사내|동호회|간담회 개최|"
                   r"주가|급등|급락|상한가|하한가|추천주|유망주|테마주|목표주가|증권가|호재|악재|"
                   r"운세|날씨|스포츠|연예|칼럼|사설|인터뷰|기고|오피니언|만평|"
                   r"축사|개회사|표창|공모전|festival|축제)")

# 정치 공방·지역 행사 등 투자 재료가 아닌 것만 제외 (나머지는 통과)
KR_DROP = re.compile(r"(요구|반발|공방|논란|비판|성토|규탄|촉구|해명|의혹|"
                     r"의원|대표는|당은|여당|야당|국정감사|대정부질문|"
                     r"맞손|업무협약 체결|간담회|토론회|세미나 개최|포럼 개최|박람회|"
                     r"카지노|헴프|축제)")

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
    """종목만 추출. 국내=6자리 숫자, 미국=US: 접두사 (산업 약어와 혼동 방지)"""
    kr, us = [], []
    for w in load_watchlist():
        w = w.strip()
        if re.fullmatch(r"\d{6}", w):
            kr.append(w)
        elif w.upper().startswith("US:"):
            t = w.split(":", 1)[1].strip().upper()
            if re.fullmatch(r"[A-Z.\-]{1,6}", t):
                us.append(t)
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

COVER = re.compile(r"(금융위원회|한국거래소|회\s*사\s*명|대\s*표\s*이\s*사|본\s*점\s*소\s*재\s*지|"
                   r"작\s*성\s*책\s*임\s*자|전\s*화\s*번\s*호|홈페이지|전자우편|담당자|"
                   r"정정대상 공시서류|제출일|귀중)")

def dart_body(rcept_no, report_nm, corp_code, key, limit=700):
    """공시 원문(document.xml)을 받아 핵심 표·문장을 추출한다. 유형 무관."""
    try:
        r = requests.get("https://opendart.fss.or.kr/api/document.xml",
                         params={"crtfc_key": key, "rcept_no": rcept_no}, timeout=30)
        if r.status_code != 200 or len(r.content) < 500:
            return None
        z = zipfile.ZipFile(io.BytesIO(r.content))
        raw = z.read(z.namelist()[0])
        for enc in ("euc-kr", "cp949", "utf-8"):
            try:
                html = raw.decode(enc); break
            except Exception:
                continue
        else:
            return None
        # 표를 "항목: 값" 형태로
        pairs = []
        for tr in re.findall(r"(?is)<TR[^>]*>(.*?)</TR>", html):
            cells = [re.sub(r"(?s)<[^>]+>", " ", c) for c in re.findall(r"(?is)<T[DEH][^>]*>(.*?)</T[DEH]>", tr)]
            cells = [re.sub(r"&[a-z]+;|&#\d+;", " ", c) for c in cells]
            cells = [re.sub(r"\s+", " ", c).strip() for c in cells]
            cells = [c for c in cells if c and c not in ("-", "－")]
            if len(cells) >= 2:
                k, v = cells[0][:28], " ".join(cells[1:])[:60]
                if not (k and v and len(k) > 1) or k.startswith("주"):
                    continue
                if COVER.search(k):        # 모든 공시에 붙는 표지 — 버림
                    continue
                pairs.append(f"{k}: {v}")
        out = " · ".join(pairs[:14])
        if len(out) < 40:
            txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
            txt = re.sub(r"(?s)<[^>]+>", " ", txt)
            txt = re.sub(r"&[a-z]+;|&#\d+;", " ", txt)
            txt = re.sub(r"\s+", " ", txt).strip()
            out = txt[:limit]
        return out[:limit] if out and len(out) > 30 else None
    except Exception:
        return None

_COMPANY = {}

def dart_company(corp_code, key):
    """기업개황 — 업종·설립·상장 (하루 캐시)"""
    if corp_code in _COMPANY:
        return _COMPANY[corp_code]
    info = None
    try:
        r = requests.get("https://opendart.fss.or.kr/api/company.json",
                         params={"crtfc_key": key, "corp_code": corp_code}, timeout=20)
        if r.status_code == 200:
            j = r.json()
            if j.get("status") == "000":
                info = {"induty": j.get("induty_code", ""), "ceo": j.get("ceo_nm", ""),
                        "est": (j.get("est_dt") or "")[:4], "mkt": j.get("corp_cls", ""),
                        "name": j.get("corp_name", "")}
    except Exception:
        pass
    _COMPANY[corp_code] = info
    return info

# 표준산업분류 앞 2~3자리 → 업종명 (자주 나오는 것)
INDUTY = {
 "10":"식품","11":"음료","13":"섬유","14":"의복","17":"펄프·종이","19":"석유정제",
 "20":"화학","21":"의약품","22":"고무·플라스틱","23":"비금속광물","24":"1차금속",
 "25":"금속가공","26":"전자부품·반도체","27":"의료·정밀기기","28":"전기장비",
 "29":"기계장비","30":"자동차","31":"기타운송장비(조선·항공)","32":"가구·기타제조",
 "35":"전기·가스","36":"수도","41":"건설","42":"토목·전문건설","45":"자동차판매",
 "46":"도매","47":"소매","49":"육상운송","50":"수상운송","51":"항공운송",
 "58":"출판","59":"영상·음악","61":"통신","62":"소프트웨어","63":"정보서비스",
 "64":"금융","65":"보험","66":"금융지원","68":"부동산","70":"연구개발","71":"전문서비스",
 "72":"건축기술·엔지니어링","73":"기타과학기술","86":"보건업"}

def induty_name(code):
    c = str(code or "")
    return INDUTY.get(c[:2], "")

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
    seen_rcp = set()
    for mkt, label in (("Y","유가증권"), ("K","코스닥")):
        for page in (1, 2):
            r = requests.get("https://opendart.fss.or.kr/api/list.json",
                params={"crtfc_key":key,"bgn_de":bgn,"end_de":end,"corp_cls":mkt,
                        "page_count":100,"page_no":page,"pblntf_ty":"B"}, timeout=40)
            j = r.json() if r.status_code == 200 else {}
            if j.get("status") != "000": break
            for x in j.get("list", []):
                if x.get("rcept_no") in seen_rcp: continue
                nm = x.get("report_nm","")
                ks = kind_of(nm)
                if not ks: continue
                seen_rcp.add(x.get("rcept_no"))
                sc = rev.get(x.get("corp_code"), ("", x.get("corp_name","")))
                ci = None
                if any(k in ks for k in ("의지","자본","위험","실체")) and len(out) < 40:
                    ci = dart_company(x.get("corp_code"), key)
                body = ""
                if any(k in ks for k in ("의지","자본","위험","실체")) and len(out) < 40:
                    body = dart_body(x.get("rcept_no"), nm, x.get("corp_code"), key) or ""
                prof = ""
                if ci:
                    ind = induty_name(ci.get("induty"))
                    bits = [b for b in [ind, f"{label}", f"설립 {ci['est']}" if ci.get("est") else ""] if b]
                    prof = " / ".join(bits)
                out.append(item(title=f"{x.get('corp_name')} — {nm}", core=f"{x.get('corp_name')} {nm}",
                    date=x.get("rcept_dt",""), org=f"DART·{label}", official=True, kinds=ks,
                    abstract=body, profile=prof,
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
            nm2 = x.get("report_nm","")
            out.append(item(title=f"⭐ {c['name']} — {nm2}",
                core=f"{c['name']} {nm2}", date=x.get("rcept_dt",""),
                abstract=dart_body(x.get("rcept_no"), nm2, c["code"], key) or "",
                org="DART·감시종목", official=True, kinds=kind_of(nm2) or ["일정"],
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
                body = ""
                if f.startswith(("8-K", "10-Q", "10-K")):
                    try:
                        doc = rec.get("primaryDocument", [""])[i]
                        rr = requests.get(
                            f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}",
                            headers={"User-Agent": SEC_UA}, timeout=25)
                        if rr.status_code == 200:
                            txt = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", rr.text)
                            txt = re.sub(r"(?s)<[^>]+>", " ", txt)
                            txt = re.sub(r"&[a-z]+;|&#\d+;", " ", txt)
                            txt = re.sub(r"\s+", " ", txt).strip()
                            txt = re.sub(r"(?i)\b(xbrli?|iso4217|us-gaap|dei):\S+", " ", txt)
                            txt = re.sub(r"\b[Pp]\d+[YMD]\b", " ", txt)
                            txt = re.sub(r"\s+", " ", txt)
                            # Item 조항부터 시작 — 앞의 표지·태그 잔재는 버린다
                            raw = ""
                            if f.startswith("8-K"):
                                m2 = re.search(r"(?i)(item\s+\d+\.\d+[^.]{0,90}\.)(.{200,1200})", txt)
                                raw = (m2.group(1) + m2.group(2)) if m2 else ""
                            else:
                                # 10-Q/10-K: 경영진 논의(MD&A)에서 수치 있는 문장만
                                m4 = re.search(r"(?is)(management.s discussion and analysis.{0,120})(.{400,4000})", txt)
                                seg = m4.group(2) if m4 else txt
                                sents = [s.strip() for s in re.split(r"(?<=\.)\s+", seg)
                                         if 60 < len(s) < 300 and re.search(r"\$[\d,.]+\s*(million|billion)|\d+(\.\d+)?%", s)]
                                raw = " ".join(sents[:6])
                            if len(raw) < 120:
                                m3 = re.search(r"(?i)(announc|reported|revenue|agreement|entered into|completed)(.{200,900})", txt)
                                raw = (m3.group(1)+m3.group(2)) if m3 else txt[:800]
                            kb, _ = to_ko(raw[:900])
                            body = kb or raw[:900]
                    except Exception:
                        pass
                out.append(item(title=f"⭐ {name} — {f} {lab}", core=f"{name} {f} {lab}",
                    date=d, org="SEC·감시종목", official=True, abstract=body,
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
# 경제적 조치 — 이 중 하나는 반드시 있어야 통과
POL_ACTION = ["tariff", "duty", "quota", "export control", "import restriction", "sanction",
              "entity list", "subsidy", "tax credit", "grant program", "loan guarantee",
              "price floor", "antidumping", "countervailing", "safeguard", "trade remedy",
              "supply chain", "critical mineral", "strategic reserve", "procurement",
              "emission standard", "efficiency standard", "licensing requirement",
              "approval of", "authorization for", "moratorium", "ban on", "restriction on"]
# 산업 — 이 중 하나는 반드시 있어야 통과
POL_INDUSTRY = ["semiconductor", "chip", "polysilicon", "solar", "battery", "lithium",
                "rare earth", "steel", "aluminum", "copper", "nickel", "shipbuilding", "vessel",
                "aircraft", "automobile", "vehicle", "electric vehicle", "nuclear reactor",
                "power grid", "transmission line", "natural gas", "crude", "petroleum",
                "artificial intelligence", "data center", "cloud computing", "biotechnology",
                "pharmaceutical", "medical device", "defense", "satellite", "telecommunication",
                "refrigerant", "chemical", "fertilizer", "energy", "electricity", "mineral",
                "manufacturing", "import", "export", "commodity", "machinery", "equipment"]
# 행정 잡무 — 하나라도 있으면 제외
POL_ADMIN = ["meeting notice", "advisory committee", "sunshine act", "privacy act",
             "paperwork reduction", "records schedule", "delegation of authority",
             "organization and functions", "request for nominations", "patent license",
             "government-owned invention", "senior executive service", "freedom of information",
             "system of records", "state implementation plan", "air quality designation",
             "national register of historic", "endangered species", "fishery", "hunting",
             "grazing", "schedules of controlled substances", "temporary placement"]

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
        blob = (title + " " + abst).lower()      # ← 반드시 영문 원문으로 검사
        if any(k in blob for k in POL_ADMIN): continue
        # 산업이 걸리면 통과. 경제조치는 가점 요소일 뿐 필수 아님
        if not any(k in blob for k in POL_INDUSTRY): continue
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
def _entries_from_broken_xml(text):
    """표준을 안 지키는 RSS를 정규식으로 직접 읽는다 (korea.kr 대응)"""
    out = []
    for blk in re.findall(r"(?is)<item[^>]*>(.*?)</item>", text):
        def pick(tag):
            m = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", blk)
            if not m: return ""
            v = m.group(1)
            v = re.sub(r"(?is)<!\[CDATA\[(.*?)\]\]>", r"\1", v)
            return re.sub(r"(?s)<[^>]+>", "", v).strip()
        t = pick("title")
        if t:
            out.append({"title": t, "link": pick("link"),
                        "summary": pick("description"),
                        "published": pick("pubDate") or pick("dc:date")})
    return out

def fetch_rss(url, official=False, src_kind="정책", limit=20):
    if not HAS_FEED: raise RuntimeError("feedparser 미설치")
    f = feedparser.parse(url, agent=UA)
    entries = f.entries
    if not entries:
        # 깨진 XML 대비: 직접 받아 정규식으로 읽기
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if r.status_code == 200:
                r.encoding = r.apparent_encoding or "utf-8"
                raw = _entries_from_broken_xml(r.text)
                if raw:
                    class E:
                        def __init__(s, d): s.__dict__.update(d)
                    entries = [E(d) for d in raw]
        except Exception:
            pass
    if not entries:
        raise RuntimeError(f"피드 비었음: {str(getattr(f,'bozo_exception','0건'))[:100]}")
    f = type("F", (), {"entries": entries})()
    out = []
    for e in f.entries[:limit]:
        t = getattr(e, "title", "").strip()
        core = strip_media(t)
        if NOISE.search(core): continue
        if src_kind in ("정책", "산업") and re.search(r"[가-힣]", core) and KR_DROP.search(core):
            continue
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
    """예정된 사건 — 정책 시행일 + 공개 일정"""
    out = []
    # 1) 연방관보에서 '시행일이 앞으로인 것'을 일정으로
    try:
        r = requests.get("https://www.federalregister.gov/api/v1/documents.json",
            params={"per_page":60,"order":"newest","conditions[type][]":["RULE"]},
            headers={"User-Agent":UA}, timeout=30)
        if r.status_code == 200:
            today = TODAY.strftime("%Y-%m-%d")
            for d in r.json().get("results", []):
                eff = d.get("effective_on")
                title = (d.get("title") or "")
                blob = title.lower()
                if not eff or eff <= today: continue
                if any(k in blob for k in POL_ADMIN): continue
                if not any(k in blob for k in POL_INDUSTRY): continue
                kt, _ = to_ko(title)
                out.append(item(title=f"[시행예정 {eff}] {title}", core=f"[{eff} 시행] {kt or title}",
                    date=eff, org=gloss(", ".join(a.get("name","") for a in (d.get("agencies") or [])[:1])),
                    official=True, kinds=["일정"], src_kind="일정", link=d.get("html_url",""),
                    effective=eff, abstract=f"이 규정은 {eff}부터 시행됩니다."))
    except Exception: pass
    # 2) FOMC 일정 페이지에서 날짜 추출
    try:
        r = requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                         headers={"User-Agent":UA}, timeout=20)
        if r.status_code == 200:
            yr = TODAY.year
            for m in re.finditer(r"(?is)<div class=\"fomc-meeting__month[^>]*>.*?>([A-Za-z]+)</.*?"
                                 r"<div class=\"fomc-meeting__date[^>]*>(\d+)-?(\d+)?", r.text):
                mon, d1, d2 = m.group(1), m.group(2), m.group(3) or m.group(2)
                try:
                    dt = datetime.strptime(f"{mon} {d2} {yr}", "%B %d %Y")
                except Exception:
                    continue
                ds = dt.strftime("%Y-%m-%d")
                if ds >= TODAY.strftime("%Y-%m-%d"):
                    out.append(item(title=f"[예정] FOMC {ds}", core=f"FOMC 금리 결정 {ds}", date=ds,
                        org="연준", official=True, kinds=["일정"], src_kind="일정",
                        link="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                        abstract="미국 기준금리 결정. 전후로 시장 변동성이 커질 수 있습니다."))
    except Exception: pass
    if not out: raise RuntimeError("예정 일정 0건 (시행예정 규정·FOMC 일정 미확보)")
    return out[:15]

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

def dedup(items):
    """같은 공시·같은 기사 중복 제거 (링크 기준, 뒤에 온 것은 버림)"""
    seen, out = set(), []
    for x in items:
        k = x.get("link") or x.get("core", "")
        # DART는 접수번호가 핵심
        m = re.search(r"rcpNo=(\d+)", k)
        if m: k = "dart:" + m.group(1)
        if k in seen:
            continue
        seen.add(k); out.append(x)
    return out

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
    before = len(items)
    items = dedup(items)
    for i, x in enumerate(items, 1):
        x["id"] = i
    if before != len(items):
        print(f"중복 제거: {before} → {len(items)}건")
    data = {"generated": TODAY.strftime("%Y-%m-%d %H:%M"), "date": TODAY.strftime("%Y-%m-%d"),
            "sources": sources, "errors": errors, "watchlist": load_watchlist(), "items": items,
            "coverage": "공시·정책 원문 우선. 개별 기업 주가·잡담 기사는 제외. 여기 없는 정보는 존재할 수 있음."}
    os.makedirs("data", exist_ok=True)
    for p in (f"data/raw_{data['date']}.json", "data/latest.json"):
        json.dump(data, open(p,"w",encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"수집 완료: {len(items)}건 · 원천 {len(sources)-len(errors)}/{len(sources)}")

if __name__ == "__main__":
    main()
