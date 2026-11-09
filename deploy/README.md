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
