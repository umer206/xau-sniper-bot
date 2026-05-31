# XAU Sniper Bot

Multi-timeframe MT5 scanner for Gold setups:

- H1: directional bias
- M15: demand and supply zone map
- M5: confirmation after zone interaction
- M1: sniper trigger timing
- OpenAI: final validation only after zone interaction, M5 confirmation, and a near-valid M1 trigger
- Optional external analyzer: one-shot SMC confluence from `C:\2026\CodexAlyzer\main.py`

The bot is dry-run by default. It prints signals to the console and writes JSONL signal records locally.

`h1_bias_mode` controls how selective the H1 direction engine is:

- `balanced`: EMA stack or clean HH/HL / LH/LL structure can define bias.
- `strict`: EMA stack must agree with recent swing structure.

Signal output is formatted as a trader-facing setup block:

```text
=== TRADE SETUP ===
Direction : LONG
Entry     : 4527.92, based on the bullish OB / demand zone @ 14:28 and the bullish CHOCH/BOS @ 14:38.
Stop Loss : 4525.95, below the sell-side liquidity sweep low @ 4526.10.
Target 1  : 4530.95, nearest M15 swing high liquidity @ 13:30.
Target 2  : 4535.37, extended H1 swing high liquidity @ 13:50.
R:R       : 1:1.5
Second AI : LONG (ALIGNED) | Bull 4 / Bear 1.
Confluence: Bullish H1 bias, M15 demand/support zone, M5 confirmation, M1 liquidity sweep, rejection candle, CHOCH/BOS, displacement candle.
```

When there is no entry, the bot still prints a setup-style waiting block. It
shows the bias-aligned zone first and any opposite zone as context. Opposite
zones are not traded unless H1 bias flips or reversal logic is explicitly added.

## Setup

1. Install dependencies:

```powershell
pip install -r requirements.txt
```

2. Copy config:

```powershell
Copy-Item config.example.json config.json
```

3. If OpenAI validation is enabled, set `OPENAI_API_KEY`.

```powershell
$env:OPENAI_API_KEY="your_api_key"
```

4. Start MetaTrader 5, log in, and make sure the configured symbol is visible in Market Watch.

## Run

Run one scan cycle:

```powershell
python -m xau_sniper_bot.bot --config config.json --once
```

PowerShell helpers are available too:

```powershell
.\scripts\run-once.ps1
.\scripts\start-bot-dry-run.ps1
.\scripts\watch-bot-log.ps1
.\scripts\watch-bot-status.ps1
```

For access from office laptops or iOS, see [REMOTE_ACCESS.md](REMOTE_ACCESS.md).

## Pushover Alerts

For mobile, use native Pushover notifications instead of reading a terminal.

1. Install Pushover on iPhone/iPad.
2. Create a Pushover application and copy its API token.
3. Copy your Pushover user key.
4. Set environment variables on the home MT5 laptop:

```powershell
$env:PUSHOVER_APP_TOKEN="your_app_token"
$env:PUSHOVER_USER_KEY="your_user_key"
```

5. Set `pushover_enabled` to `true` in `config.json`.
6. Send a test:

```powershell
.\scripts\test-pushover.ps1
```

By default, the bot alerts for trade setups and bot start/stop/crash events.
No-trade alerts are off by default to avoid notification spam.

If the external analyzer is enabled, make sure `groq` is installed too because
`C:\2026\CodexAlyzer\main.py` imports it:

```powershell
pip install groq
```

Run continuously:

```powershell
python -m xau_sniper_bot.bot --config config.json
```

## MT5 Execution

The bot can send approved setups to MT5 as market orders. Live execution needs
both:

- `trade_execution_enabled: true` in `config.json`
- `--live` on the command line

Without `--live`, the bot stays in dry-run mode and prints `Execution : DRY_RUN`.

```powershell
python -m xau_sniper_bot.bot --config config.json --live
```

Execution guardrails:

- Uses `trade_volume`, default `0.01`.
- Uses Target 1 as TP by default. Set `trade_take_profit_target` to `2` to use Target 2.
- Blocks duplicate positions unless `trade_allow_existing_position` is true.
- Blocks entries when spread is above `trade_max_spread`.
- Sends SL and TP with the MT5 order.

Disable OpenAI from the CLI:

```powershell
python -m xau_sniper_bot.bot --config config.json --no-openai
```

## MT5 Chart Output

The MT5 Python API does not draw directly on a chart. When `mt5_chart_bridge_enabled` is true, the bot writes the latest signal as JSON to the MT5 `MQL5/Files` folder or to `mt5_chart_bridge_path` if provided. A small MQL5 indicator or EA can read that file and display the signal on-chart.

## Signal Logic

Buy setup:

- H1 bullish bias
- M15 demand/support zone
- M1 sell-side liquidity sweep
- M1 close back above swept low
- M1 minor bullish break of structure
- Displacement and ATR filters pass
- M5 confirms bullish continuation after zone interaction
- Stop loss below swept low
- Take profit at nearest M15/H1 high liquidity

Sell setup:

- H1 bearish bias
- M15 supply/resistance zone
- M1 buy-side liquidity sweep
- M1 close back below swept high
- M1 minor bearish break of structure
- Displacement and ATR filters pass
- M5 confirms bearish continuation after zone interaction
- Stop loss above swept high
- Take profit at nearest M15/H1 low liquidity
