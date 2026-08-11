# 토스 API 연결 진단

```
🔌 토스 API 연결 진단 2026-08-11 22:32 KST
  토큰 시도 /api/v1/auth/token [json] → HTTP 401
     응답: {
  "error": {
    "referenceId": "0.3ec1c917.1786455138.1d655de7",
    "code": "edge-blocked",
    "message": "Authorization 헤더가 전달되지 않았습니다."
  }
}
  토큰 시도 /api/v1/auth/token [form] → HTTP 401
     응답: {
  "error": {
    "referenceId": "0.3bc1c917.1786455139.1a65ac80",
    "code": "edge-blocked",
    "message": "Authorization 헤더가 전달되지 않았습니다."
  }
}
  토큰 시도 /oauth/token [json] → HTTP 403
     응답: {
  "error": {
    "referenceId": "0.3bc1c917.1786455139.1a65ad07",
    "code": "edge-blocked",
    "message": "요청한 API 경로를 지원하지 않습니다."
  }
}
  토큰 시도 /oauth/token [form] → HTTP 403
     응답: {
  "error": {
    "referenceId": "0.3ec1c917.1786455139.1d65611e",
    "code": "edge-blocked",
    "message": "요청한 API 경로를 지원하지 않습니다."
  }
}
  토큰 시도 /api/v1/oauth/token [json] → HTTP 401
     응답: {
  "error": {
    "referenceId": "0.3ec1c917.1786455139.1d6561f2",
    "code": "edge-blocked",
    "message": "Authorization 헤더가 전달되지 않았습니다."
  }
}
  토큰 시도 /api/v1/oauth/token [form] → HTTP 401
     응답: {
  "error": {
    "referenceId": "0.3bc1c917.1786455139.1a65ae30",
    "code": "edge-blocked",
    "message": "Authorization 헤더가 전달되지 않았습니다."
  }
}
❌ 토큰 발급 실패 — 아래 시도 기록을 Claude에게 전달하세요.
   (원인 후보: 키 오타 / 승인 대기 / 인증 경로가 문서와 다름)
※ 이 진단기는 공개 시세만 호출합니다. 계좌·주문 기능 없음.
```
