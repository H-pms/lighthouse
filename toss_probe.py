# -*- coding: utf-8 -*-
"""
토스증권 Open API 연결 진단기 p5a
목적: 토큰 발급 → 시세 조회 성공 여부를 확인하고 결과를 텔레그램으로 보고.
철칙: 공개 데이터(시세·종목정보)만 호출한다. 계좌/주문 엔드포인트는 이 코드에 존재하지 않는다.
"""
import os, json
from datetime import datetime, timezone, timedelta
import requests

KST = timezone(timedelta(hours=9))
BASE = "https://openapi.tossinvest.com"
TOKEN_PATHS = ["/api/v1/auth/token", "/oauth/token", "/api/v1/oauth/token"]
QUOTE_PATHS = ["/api/v1/market/quote", "/api/v1/stocks/{code}/price",
               "/api/v1/market-data/quote", "/api/v1/quotes"]
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
    """여러 표준 경로를 시도한다. OAuth2 client_credentials."""
    for path in TOKEN_PATHS:
        for style in ("json", "form"):
            try:
                url = BASE + path
                kw = {"timeout": 30}
                data = {"grant_type": "client_credentials",
                        "client_id": cid, "client_secret": secret}
                if style == "json":
                    kw["json"] = data
                else:
                    kw["data"] = data
                r = requests.post(url, **kw)
                log.append(f"  토큰 시도 {path} [{style}] → HTTP {r.status_code}")
                if r.status_code == 200:
                    j = r.json()
                    tok = j.get("access_token") or j.get("accessToken") or \
                          (j.get("data") or {}).get("access_token")
                    if tok:
                        log.append(f"  ✅ 토큰 획득 (경로 {path}, {style})")
                        return tok, path
                    log.append(f"  ⚠️ 200이나 토큰 필드 못 찾음: {json.dumps(j)[:150]}")
                elif r.status_code in (400, 401, 403):
                    log.append(f"     응답: {r.text[:150]}")
            except Exception as e:
                log.append(f"  토큰 시도 {path} [{style}] → {type(e).__name__}: {str(e)[:80]}")
    return None, None

def try_quote(token, log):
    h = {"Authorization": f"Bearer {token}"}
    for path in QUOTE_PATHS:
        url = BASE + path.replace("{code}", TEST_CODE)
        params = {} if "{code}" in path else {"code": TEST_CODE, "symbol": TEST_CODE}
        try:
            r = requests.get(url, headers=h, params=params, timeout=30)
            log.append(f"  시세 시도 {path} → HTTP {r.status_code}")
            if r.status_code == 200:
                body = r.text[:400]
                log.append(f"  ✅ 시세 응답 수신: {body}")
                return True
        except Exception as e:
            log.append(f"  시세 시도 {path} → {type(e).__name__}: {str(e)[:80]}")
    return False

def main():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    log = [f"🔌 토스 API 연결 진단 {now} KST"]
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
