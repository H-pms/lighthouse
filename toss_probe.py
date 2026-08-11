# -*- coding: utf-8 -*-
"""
토스증권 Open API 연결 진단기 p5a-2 (공식 사양 반영: /oauth2/token, form)
목적: 토큰 발급 → 시세 조회 성공 여부를 확인하고 결과를 텔레그램으로 보고.
철칙: 공개 데이터(시세·종목정보)만 호출한다. 계좌/주문 엔드포인트는 이 코드에 존재하지 않는다.
"""
import os, json
from datetime import datetime, timezone, timedelta
import requests

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.tossinvest.com"
TOKEN_PATH = "/oauth2/token"   # 공식 사양 [확인]
STOCK_PATH = "/api/v1/stocks"  # 종목 기본정보 [확인]
PRICE_PATH = "/api/v1/prices"  # 현재가 [확인]
TEST_CODE = "005930"  # 삼성전자

def tg(text):
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

def get_token(cid, secret, log):
    """공식 사양: POST /oauth2/token, form-urlencoded, client_credentials"""
    try:
        r = requests.post(BASE + TOKEN_PATH,
                          data={"grant_type": "client_credentials",
                                "client_id": cid, "client_secret": secret},
                          headers={"Content-Type": "application/x-www-form-urlencoded"},
                          timeout=30)
        log.append(f"  토큰 요청 {TOKEN_PATH} → HTTP {r.status_code}")
        if r.status_code == 200:
            tok = r.json().get("access_token")
            if tok:
                log.append("  ✅ 토큰 발급 성공")
                return tok, TOKEN_PATH
            log.append(f"  ⚠️ 200이나 access_token 없음: {r.text[:150]}")
        else:
            log.append(f"     응답: {r.text[:250]}")
            if r.status_code == 403:
                log.append("  ⛔ 403 = 허용 IP 미등록 가능성 — 이 실행 환경의 IP를")
                log.append("     토스 WTS 설정>Open API>허용 IP 관리에 등록해야 합니다.")
    except Exception as e:
        log.append(f"  토큰 요청 실패 {type(e).__name__}: {str(e)[:100]}")
    return None, None

def try_quote(token, log):
    h = {"Authorization": f"Bearer {token}"}
    ok = False
    for label, path, params in [("종목정보", STOCK_PATH, {"symbols": TEST_CODE}),
                                ("현재가", PRICE_PATH, {"symbols": TEST_CODE})]:
        try:
            r = requests.get(BASE + path, headers=h, params=params, timeout=30)
            log.append(f"  {label} {path} → HTTP {r.status_code}")
            if r.status_code == 200:
                log.append(f"  ✅ {label} 응답: {r.text[:250]}")
                ok = True
            else:
                log.append(f"     응답: {r.text[:200]}")
        except Exception as e:
            log.append(f"  {label} 실패 {type(e).__name__}: {str(e)[:80]}")
    return ok

def main():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    log = [f"🔌 토스 API 연결 진단 {now} KST"]
    try:
        myip = requests.get("https://api.ipify.org", timeout=10).text.strip()
        log.append(f"  이 실행 환경의 공인 IP: {myip}  ← 토스 '허용 IP 관리'에 등록 필요")
    except Exception:
        log.append("  (IP 확인 실패)")
    cid, secret = os.environ.get("TOSS_CLIENT_ID"), os.environ.get("TOSS_CLIENT_SECRET")
    if not cid or not secret:
        log.append("❌ 금고에 TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 이 없습니다.")
        print("\n".join(log)); tg("\n".join(log)); return

    token, tpath = get_token(cid, secret, log)
    if not token:
        log.append("❌ 토큰 발급 실패 — 아래 시도 기록을 Claude에게 전달하세요.")
        log.append("   (원인 후보: 키 오타 / 승인 대기 / 인증 경로가 문서와 다름)")
    else:
        ok = try_quote(token, log)
        log.append("✅ 연결 성공 — 시세 조회까지 확인" if ok else
                   "⚠️ 토큰은 성공, 시세 경로 미확인 — 공식 문서의 정확한 엔드포인트 필요")
    log.append("※ 이 진단기는 공개 시세만 호출합니다. 계좌·주문 기능 없음.")
    out = "\n".join(log)
    print(out)
    os.makedirs("briefing", exist_ok=True)
    with open("briefing/toss_probe.md", "w", encoding="utf-8") as f:
        f.write("# 토스 API 연결 진단\n\n```\n" + out + "\n```\n")
    tg(out)

if __name__ == "__main__":
    main()
