# KIS MCP Server — read-only foundation

한국투자증권 **KIS Developers Open API**를 통해 본인 계좌 잔고를 MCP에서 안전하게 조회하기 위한 Python 프로젝트입니다.

> **개발 상태:** 인증 및 국내주식 잔고조회 뼈대 구현. 실제 한국투자증권 계정 연결 및 ISA 조회 성공은 아직 검증되지 않았습니다. 주문·매도·환전·이체 API는 **구현하지 않았습니다**.

## 목적

- 한국투자증권에 보유한 **중개형 ISA** 내 국내 상장 ETF를 파악하고, 나무증권 보유자산과 합산하여 포트폴리오 편중을 분석
- 한국투자증권 잔고 조회 결과를 종목코드·수량·평가금액·예수금 단위로 표준화
- 비밀번호·API 키·계좌번호를 MCP 응답이나 GitHub 로그에 노출하지 않음
- 과세혜택·납입한도·ISA 만기를 **임의 추정하지 않음**; Open API 제공 범위를 따로 검증

## 준비

1. [KIS Developers](https://apiportal.koreainvestment.com/)에서 실전투자 Open API 사용 신청 및 앱키/시크릿 발급
2. 본인 중개형 ISA가 KIS Open API를 통한 **조회 가능한 계좌인지** 증권사 API 가이드에서 확인
3. `cp .env.example .env` 후 **본인 컴퓨터에서만** `.env` 입력. 절대 GitHub, 대화, PR에 값을 올리지 않기
4. Python 3.11+ 설치 후 아래 실행

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m kis_mcp
```

MCP 클라이언트의 stdio 서버 설정:

```json
{
  "mcpServers": {
    "kis-readonly": {
      "command": "/ABS/PATH/KIS_MCP_Sever/.venv/bin/python",
      "args": ["-m", "kis_mcp"],
      "env": {
        "KIS_ENV": "real"
      }
    }
  }
}
```

`python -m kis_mcp`는 설정에 필요한 비밀값을 **로컬 환경 변수 또는 프로젝트 루트 .env**에서 읽습니다. 프로세스의 표준출력은 MCP 프로토콜 전용입니다.

## 도구

| MCP 도구 | 기능 |
| --- | --- |
| `kis_connection_status` | 실행환경·읽기전용 상태·설정 유무 (비밀값 제외) |
| `kis_domestic_balance` | 국내 잔고와 평가·예수금 **조회 전용** |
| `kis_portfolio_export` | 나무/NH 통합을 위한 개인정보 제거 표준 포맷 |

ISA 전용 메타데이터(납입한도, ISA 만기, 계좌유형)의 존재 여부를 **이 도구 결과만으로 확정하지 않습니다**. 해당 정보는 추후 별도 API와 대조해야 합니다.

## 주의사항

- 계좌번호는 환경변수 `KIS_CANO`(8자리), `KIS_ACNT_PRDT_CD`(2자리)로 분리해 사용
- 실전·모의 REST 도메인을 고정하고 임의 URL을 받지 않음
- API 응답 `rt_cd` 실패 시 예외; 일부 페이지만 성공했을 경우 전체 성공으로 보고하지 않음
- 응답은 허용된 필드만 반환하고 계좌번호·토큰·원시 개인정보 제외
- API가 ISA 조회에 미지원·거부를 반환할 수 있음. **일반 계좌 조회와 ISA 조회를 동일시하지 말 것**
- 국내·해외 통합 시 예수금/증거금/미결제 중복 계상 금지
- 매매 기능 추가는 별도 설계·테스트·승인 절차 필요. 현재 저장소에는 매매 엔드포인트가 없음

## 참고

- [한국투자증권 공식 API 포털](https://apiportal.koreainvestment.com/docs)
- [한국투자증권 공식 샘플 코드](https://github.com/koreainvestment/open-trading-api)


## ISA 계좌 유형 및 포트폴리오 합산

계좌 소유자가 ISA 계좌임을 확인했을 때만 로컬 `.env`에 `KIS_ISA_USER_CONFIRMED=true`를 설정합니다. 서버 응답에는 `account_type_source=user_confirmed`로 표시하며 API 자체의 ISA 인증을 주장하지 않습니다. `kis_portfolio_export`는 종목별 원화 평가액과 브로커 원화 예수금을 별도 필드로 제공합니다. 예수금은 주문가능금액으로 확정하지 않으며 총자산에 중복 합산하지 않습니다.
