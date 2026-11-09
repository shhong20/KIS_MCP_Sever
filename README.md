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

## 나무증권 통합 종목조회 (2026-11)

\`kis_compare_namuh_snapshot\`는 나무증권 플러그인의 `portfolio_overview` 응답 JSON을 **호출자가 제공하면**, 한국투자증권 ISA를 새로 조회하고 종목별 보유수량·평가액을 합산합니다. 동일 종목도 거래소/국가가 다르면 다른 종목으로 유지합니다. 나무증권 자료는 KIS 서버가 원본을 인증하지 않으므로 `nh_input_provenance=caller_supplied_not_authenticated`로 표시됩니다. `portfolio_net_asset_audit`의 결과가 검증되지 않은 경우 입력 `namuh_audit_status=UNRECONCILED_ACCOUNTING`으로 전달할 수 있습니다.

**현금·예수금·증거금·미결제금·총자산 및 실현손익은 단순 합산하지 않습니다.** 결측치나 합계 불일치가 있으면 결과를 반환하지 않습니다. 완전한 통합 순자산·실제 투자수익률은 해당 증권사의 외부 입출금까지 검증되기 전까지 null입니다.

## ISA 주문가능금액 조회 (주문 실행 없음)

`kis_domestic_buying_power(symbol, limit_price_krw)`는 KIS 공식 국내주식 `inquire-psbl-order`(GET, 실전 `TTTC8908R`)를 사용해 지정 종목·지정가 기준 미수 없는 매수가능금액과 수량을 확인합니다. `nrcvb_buy_amt`/`nrcvb_buy_qty`를 기준으로 하며 `max_buy_amt`는 증거금·신용을 포함할 가능성이 있어 권장 금액으로 사용하지 않습니다. 예수금 `dnca_tot_amt`와 주문가능금액은 다를 수 있습니다. 이 API는 주문 접수가 불가능하며, 계좌 인증 실패나 미지원 시 에러를 돌려줍니다. 상품의 종류·장중 시세·계좌 정책에 따라 결과가 달라집니다.


## ETF 공식 구성종목 자동 스냅샷 (부분 범위)

`python -m kis_mcp.etf_official`은 **PLUS 고배당주(161510) 한화자산운용 공식 페이지**에서 현재 화면에 표시된 구성종목만 가져옵니다. 기준일/소스 URL/원본 SHA-256/커버리지/구성종목 수를 검증하고 권한 0600 JSON 캐시에 원자적으로 기록합니다. 이 페이지는 기본 10개만 표시하므로 *나머지 20개는 UNKNOWN*으로 남기고 100%로 비례 확대하지 않습니다. 오래됐거나 HTML 구조가 달라진 경우 이전 캐시는 덮어쓰지 않습니다. 캐시는 5일 이내일 때만 통합 자산배분 MCP에 자동 연결합니다. 외부 정보가 실제 운용사 확인까지 완료된 것으로 표현되지 않도록 상태값을 `OFFICIAL_ISSUER_CACHE_PARTIAL_NOT_ATTESTED`로 표시합니다. 다른 5개 목표 ETF는 공식 편입비 데이터 파서를 확보하기 전까지 미지원으로 남깁니다.

운영 스케줄은 사용자 systemd 타이머 `kis-etf-composition-refresh.timer`를 통해 평일 09:40/18:10(KST)에 실행합니다. 거래·주문·잔고 조작은 전혀 하지 않습니다.
