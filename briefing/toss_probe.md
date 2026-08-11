# 토스 API 연결 진단

```
🔌 토스 API 연결 진단 2026-08-11 22:48 KST
  이 실행 환경의 공인 IP: 172.183.135.154  ← 토스 '허용 IP 관리'에 등록 필요
  토큰 요청 /oauth2/token → HTTP 403
     응답: {"error":"access_denied","error_description":"IP address not allowed"}
  ⛔ 403 = 허용 IP 미등록 가능성 — 이 실행 환경의 IP를
     토스 WTS 설정>Open API>허용 IP 관리에 등록해야 합니다.
❌ 토큰 발급 실패 — 아래 시도 기록을 Claude에게 전달하세요.
   (원인 후보: 키 오타 / 승인 대기 / 인증 경로가 문서와 다름)
※ 이 진단기는 공개 시세만 호출합니다. 계좌·주문 기능 없음.
```
