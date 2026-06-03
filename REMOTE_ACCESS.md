# Remote Operations

This guide describes a generic remote-operations pattern for running the bot on
one primary MetaTrader 5 host while viewing logs and status from separate client
machines.

## Recommended Architecture

- Run MetaTrader 5 and the bot on one primary host.
- Use the bot log file as the shared terminal feed.
- Use the status heartbeat file to confirm the bot is running.
- Use notification delivery for trade, execution, and health alerts.
- Avoid running multiple live bot instances against the same account.

## Primary MT5 Host

Prepare the machine that has MetaTrader 5 installed and logged in.

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Copy the example configuration:

```powershell
Copy-Item config.example.json config.json
```

3. Keep secrets outside Git. Use a local `.env` file or environment variables:

```text
OPENAI_API_KEY=
GROQ_API_KEY=
PUSHOVER_APP_TOKEN=
PUSHOVER_USER_KEY=
```

4. Confirm a dry-run scan works:

```powershell
.\scripts\run-once.ps1
```

5. Start continuous dry-run mode:

```powershell
.\scripts\start-bot-dry-run.ps1
```

6. Use live execution only after configuration and dry-run behavior are verified:

```powershell
.\scripts\start-bot-live.ps1
```

## Remote Client Access

Remote clients should connect to the primary host instead of running separate
bot copies. Common options include:

- A secure remote development tunnel.
- A private network overlay.
- Remote desktop software approved for the environment.

Once connected to the project folder on the primary host, useful commands are:

```powershell
.\scripts\watch-bot-log.ps1
.\scripts\watch-bot-status.ps1
.\scripts\run-once.ps1
```

Avoid starting multiple live bot processes. If live mode is already running,
use the log and status watchers for monitoring.

## Notifications

Pushover can send concise alerts without requiring a remote terminal session.
Configure credentials with environment variables or a local `.env` file:

```text
PUSHOVER_APP_TOKEN=
PUSHOVER_USER_KEY=
```

Then enable alerts in `config.json`:

```json
"pushover_enabled": true
```

Send a test notification:

```powershell
.\scripts\test-pushover.ps1
```

Default alerts include:

- Valid LONG/SHORT setup.
- Execution status.
- Scan-summary setup block.
- Bot started, stopped, or crashed.

## Shared Log Feed

Every bot run writes console output to:

```text
logs\bot.log
```

Watch the shared feed:

```powershell
.\scripts\watch-bot-log.ps1
```

## Bot Status Heartbeat

Every bot run updates:

```text
runtime\status.json
```

Watch bot status:

```powershell
.\scripts\watch-bot-status.ps1
```

Status meanings:

- `RUNNING`: the bot is alive and updating heartbeat.
- `STOPPED`: the bot stopped gracefully.
- `ERROR`: the bot crashed and wrote the error.
- `OFFLINE`: status was `RUNNING`, but the heartbeat is stale.

Default stale threshold is 180 seconds. Override it if needed:

```powershell
.\scripts\watch-bot-status.ps1 -StaleSeconds 90
```

## Safety Rules

- Run the live bot on one primary host only.
- Do not run duplicate live bot instances against the same account.
- Keep `--live` disabled until real execution is intentional.
- Use `.\scripts\start-bot-dry-run.ps1` for monitoring and validation.
- Use `.\scripts\start-bot-live.ps1` only when live execution is intended.
- Keep `.env`, `config.json`, logs, runtime files, and signal output out of Git.
- Do not expose local ports publicly unless the access layer is secured.

## Troubleshooting

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

- MetaTrader 5 is open.
- The trading account is logged in.
- The configured symbol is visible in Market Watch.
- The symbol name in `config.json` matches the broker.
