# WSL deployment / dedicated tunnel

The main MCP server uses **stdio**. It does not run constantly on its own;
the tunnel client starts it for an MCP session. Do not create a zombie stdio
systemd daemon. A dedicated tunnel client is the long-lived user service.

1. Clone to `/home/hong/KIS_MCP_Sever`, create `.venv`, install `pip install -e .`.
2. Put `KIS_APP_KEY`, `KIS_APP_SECRET`, `KIS_CANO` (8 digits) and `KIS_ACNT_PRDT_CD` (2 digits) in project-local `.env`, mode 0600. Never commit credentials.
3. Create a **separate** KIS tunnel in the OpenAI tunnel settings. Do not reuse the Namuh tunnel ID.
4. Copy `kis-portfolio.yaml.example` to `~/.config/tunnel-client/kis-portfolio.yaml` and replace the tunnel ID. Set mode 0600.
5. Put `CONTROL_PLANE_API_KEY=...` in `~/.config/kis-mcp/tunnel-runtime.env` with mode 0600. This is the **OpenAI tunnel runtime key**, not the KIS brokerage key; keep these separate.
6. Install the user service:

```bash
install -m 0644 deploy/kis-mcp-tunnel.service ~/.config/systemd/user/kis-mcp-tunnel.service
systemctl --user daemon-reload
systemctl --user enable --now kis-mcp-tunnel.service
systemctl --user status kis-mcp-tunnel.service --no-pager
```

The service uses `ConditionPathExists` so it will not start until the dedicated tunnel profile exists. Existing Namuh service is independent. Configure the tunnel at the control plane/ChatGPT connector UI after it is running.

Before publishing to ChatGPT, verify the local MCP tools in stdio and confirm the `kis_connection_status` response shows `trading_enabled=false`. If KIS refuses ISA balance, **do not substitute a normal-account response**.

Operational rule: no placing orders, exchange operations, withdrawals or transfers, and no credentials in logs. If account scope or query fails, fail closed and investigate official KIS API eligibility.

## 독립 일별 ISA 로컬 저장 예약 작업

NH 나무증권의 로컬 스냅샷이 매일 20:30 KST에 실행되므로, KIS는 평일 20:35 KST에 저장합니다.
WSL 중단으로 실행하지 못한 날을 오늘의 데이터로 잘못 채우지 않도록 Persistent=false를 사용합니다.
별도의 계좌번호·키는 systemd 단위 파일에 저장하지 않고 작업 폴더의 chmod 600 .env만 사용합니다.

WSL 사용자 환경에서:

  install -m 0644 deploy/kis-portfolio-snapshot.service ~/.config/systemd/user/kis-portfolio-snapshot.service
  install -m 0644 deploy/kis-portfolio-snapshot.timer ~/.config/systemd/user/kis-portfolio-snapshot.timer
  systemctl --user daemon-reload
  systemctl --user enable --now kis-portfolio-snapshot.timer
  systemctl --user list-timers --all | grep kis-portfolio-snapshot

서비스는 읽기전용 조회·비공개 저장만 수행합니다. 당일 마감 전 수동 실행 시에는 해당 날짜 스냅샷이 조기 고정될 수 있으므로
운영 환경에서는 오후 20:35 자동 실행 결과를 확인하세요. 운영자는 journalctl --user -u kis-portfolio-snapshot.service를 통해
KIS_SNAPSHOT_OK 또는 KIS_SNAPSHOT_FAILED 상태를 확인할 수 있지만 계좌번호/잔고 세부값은 기록하지 않습니다.
휴장일은 자동 판정하지 못하므로 날짜별 기록의 시장거래일 여부는 후속 보고에서 별도 확인해야 합니다.
