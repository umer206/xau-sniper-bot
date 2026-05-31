# Remote Terminal Access

This setup keeps MT5 and the execution bot on the home laptop, then lets other
devices view/control the same project terminal remotely.

Recommended stack:

- VS Code Remote Tunnel for the remote project and terminal.
- `logs/bot.log` as the shared live terminal feed.
- Pushover for readable iOS trade/status notifications.
- Tailscale as a backup access layer.
- MT5 mobile only for monitoring/closing trades, not for running the bot.

## Home MT5 Laptop

Do this on the laptop that has MT5 installed and logged in.

1. Install VS Code.

2. Confirm the VS Code CLI is available:

```powershell
code --version
```

If PowerShell cannot find `code`, reinstall VS Code with "Add to PATH" enabled.

3. Install Python dependencies:

```powershell
cd C:\Users\DELL\OneDrive\Documents\XAUAlayzer
pip install -r requirements.txt
```

4. Confirm local dry-run works:

```powershell
.\scripts\run-once.ps1
```

5. Start the tunnel once interactively:

```powershell
.\scripts\start-vscode-tunnel.ps1
```

Sign in when prompted. Use the same GitHub or Microsoft account on other
devices.

6. After the tunnel works, install it as a background service:

```powershell
.\scripts\install-vscode-tunnel-service.ps1
```

This keeps the VS Code tunnel available after restarts, as long as the laptop is
awake and online.

7. Start the bot in dry-run mode:

```powershell
.\scripts\start-bot-dry-run.ps1
```

For live execution only after testing:

```powershell
.\scripts\start-bot-live.ps1
```

## Office Laptop 1 and Laptop 2

Option A: VS Code Desktop

1. Install VS Code.
2. Install the `Remote - Tunnels` extension.
3. Sign in with the same GitHub or Microsoft account.
4. Run `Remote Tunnels: Connect to Tunnel` from the Command Palette.
5. Select `xau-mt5-home`.
6. Open:

```text
C:\Users\DELL\OneDrive\Documents\XAUAlayzer
```

Useful terminal commands:

```powershell
.\scripts\watch-bot-log.ps1
.\scripts\watch-bot-status.ps1
.\scripts\run-once.ps1
.\scripts\start-bot-dry-run.ps1
.\scripts\start-bot-live.ps1
```

Option B: Browser

Open:

```text
https://vscode.dev
```

Sign in, connect to the tunnel, and open the same project folder.

## iPhone / iPad

For day-to-day mobile use, prefer Pushover notifications plus MT5 mobile.
Use Safari/VS Code only when you need remote commands.

Browser fallback:

```text
https://vscode.dev
```

Sign in with the same account and connect to `xau-mt5-home`.

Best iOS commands:

```powershell
.\scripts\watch-bot-status.ps1
.\scripts\watch-bot-log.ps1
.\scripts\run-once.ps1
```

Avoid typing long live-execution commands from iOS unless necessary. Use MT5
mobile to monitor or manually close trades.

## Pushover Mobile Alerts

Pushover gives readable native iOS notifications without opening a web UI.

1. Install Pushover on iPhone/iPad.
2. Register a Pushover application.
3. On the home laptop, set:

```powershell
$env:PUSHOVER_APP_TOKEN="your_app_token"
$env:PUSHOVER_USER_KEY="your_user_key"
```

4. In `config.json`, set:

```json
"pushover_enabled": true
```

5. Send a test:

```powershell
.\scripts\test-pushover.ps1
```

Default alerts:

- Valid LONG/SHORT setup
- Execution status
- Bot started
- Bot stopped
- Bot crashed

No-trade alerts stay off unless `pushover_alert_no_trade` is set to `true`.

## Shared Terminal Feed

Every bot run now writes to:

```text
logs\bot.log
```

Any device can watch the same live feed:

```powershell
.\scripts\watch-bot-log.ps1
```

This is more reliable than trying to mirror one interactive PowerShell window.

## Bot Status Heartbeat

Every bot run updates:

```text
runtime\status.json
```

Watch it from any remote device:

```powershell
.\scripts\watch-bot-status.ps1
```

Meanings:

- `RUNNING`: the bot is alive and updating heartbeat.
- `STOPPED`: the bot stopped gracefully.
- `ERROR`: the bot crashed and wrote the error.
- `OFFLINE`: status was `RUNNING`, but the heartbeat is stale.

Default stale threshold is 180 seconds. Override it if needed:

```powershell
.\scripts\watch-bot-status.ps1 -StaleSeconds 90
```

## Safety Rules

- Run the bot on one machine only: the home MT5 laptop.
- Other devices should connect to that machine, not run separate bot copies.
- Keep `--live` disabled until you deliberately want execution.
- Use `.\scripts\start-bot-dry-run.ps1` for monitoring.
- Use `.\scripts\start-bot-live.ps1` only when you accept real MT5 execution.
- Keep the laptop awake and plugged in.
- Do not expose ports manually on your router.

## Backup Access With Tailscale

Install Tailscale on:

- Home MT5 laptop
- Office laptop 1
- Laptop 2
- iPhone/iPad

This gives you a private network path if the VS Code tunnel needs recovery.
Use it for RDP or other emergency access, not as the primary bot interface.

## Troubleshooting

Check tunnel status:

```powershell
code tunnel status
```

Restart the tunnel manually:

```powershell
.\scripts\start-vscode-tunnel.ps1
```

Watch the bot log:

```powershell
.\scripts\watch-bot-log.ps1
```

Watch bot status:

```powershell
.\scripts\watch-bot-status.ps1
```

Run one safe scan:

```powershell
.\scripts\run-once.ps1
```

If MT5 data fails, make sure:

- MT5 is open.
- The account is logged in.
- `XAUUSD` is visible in Market Watch.
- The symbol name in `config.json` matches your broker.
