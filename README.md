# XAU Sniper Bot

Multi-timeframe MetaTrader 5 scanner and execution assistant for XAUUSD setups.

- H1: directional bias
- M15: demand and supply zone map
- M5: confirmation after zone interaction
- M1: sniper trigger timing
- OpenAI: optional final validation after a near-valid setup forms
- Optional external analyzer: local SMC confluence and Groq-backed validation

The bot is dry-run by default. It prints signals to the console and writes JSONL signal records locally.

## Top-Down Framework

The bot now runs a full framework layer above the existing sniper trigger:

- W1, D1, H4, H1, and M15 XAUUSD analysis
- MA50/MA200, RSI, MACD, swing structure, BOS/CHOCH, FVG, and S/R scoring
- Optional DXY analysis across the same framework timeframes
- Final bias score, confidence cap at 85%, and setup plan context
- Hard blocks for MA sandwich zones, 00:00-06:00 UTC thin liquidity, configured high-impact news windows, weekly-bias conflict, and missing/misaligned DXY confirmation

The framework decides whether the bot is allowed to hunt. The existing M5/M1
logic still has to confirm the exact execution trigger before any signal emits.

Key settings:

```json
"analysis_framework_enabled": true,
"dxy_symbol": "DXY",
"dxy_confirmation_required": true,
"analysis_ma_sandwich_timeframes": ["D1", "H4", "H1"],
"high_impact_news_windows_utc": []
```

If your broker uses another DXY symbol name, set `dxy_symbol` in `config.json`.
When DXY confirmation is required and DXY is unavailable, the framework blocks
trades instead of treating the missing feed as confirmation.

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

For generic remote-operation guidance, see [REMOTE_ACCESS.md](REMOTE_ACCESS.md).

## Pushover Alerts

Use Pushover notifications for concise trade, execution, and bot-status alerts.

1. Install Pushover where alerts should be received.
2. Create a Pushover application and copy its API token.
3. Copy your Pushover user key.
4. Set environment variables on the MT5 host:

```powershell
$env:PUSHOVER_APP_TOKEN="your_app_token"
$env:PUSHOVER_USER_KEY="your_user_key"
```

Or create a local `.env` file beside `config.json`:

```text
PUSHOVER_APP_TOKEN=your_app_token
PUSHOVER_USER_KEY=your_user_key
```

5. Set `pushover_enabled` to `true` in `config.json`.
6. Send a test:

```powershell
.\scripts\test-pushover.ps1
```

By default, the bot alerts for trade setups and bot start/stop/crash events.
It also sends one scan-summary setup block after each scan. Repeated no-trade
spam remains off unless `pushover_alert_no_trade` is set to `true`.

If the external analyzer is enabled and uses Groq, make sure `groq` is installed:

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
- Blocks duplicate setup execution with `runtime/trade_lock.json`.
- Blocks entries when spread is above `trade_max_spread`.
- Sends SL and TP with the MT5 order.

## Liquidity And Volume Proxies

Forex has no centralized order book, so the bot uses proxies:

- Bid/ask spread quality
- Session context
- Smooth versus jumpy M1 price action
- M1 tick-volume spike on the sweep/trigger
- Previous highs/lows, equal highs/lows, and consolidation boundaries

These are controlled by:

```json
"liquidity_filter_enabled": true,
"max_liquidity_spread": 0.50,
"min_trigger_volume_multiplier": 1.25,
"min_sweep_volume_multiplier": 1.10
```

Trade setup output includes a `Liquidity` line with spread, volume multipliers,
session, and detected liquidity pools. Waiting / `NO TRADE` output includes the
current M1 tick-volume multiplier and spread/session/pool context so you can see
market conditions before the trigger is complete.

## Zone Freshness

The bot now treats M15 zones as conditional plans with age and distance context,
not predictions. `NO TRADE` output includes a `Zone` line showing whether the
nearest aligned zone is near/far and fresh/stale/expired.

```json
"zone_stale_after_hours": 12.0,
"zone_expire_after_hours": 36.0,
"zone_near_threshold_points": 5.0
```

Expired zones are ignored for entry scanning. Matching zones are checked nearest
first, so the waiting reason should match the zone displayed in the setup block.
Repeated Pushover scan summaries for the same setup are limited by:

```json
"pushover_scan_summary_min_interval_minutes": 15
```

## Continuation Mode

The original strategy waited for price to retest an M15 supply/demand zone. When
`continuation_mode_enabled` is true, the bot can also build nearer M5 or M1
continuation pullback zones after a confirmed breakdown or breakout.

For bearish continuation, the bot needs:

- H1 bearish bias
- M5 close below EMA20 and EMA50
- Recent M5 bearish displacement
- Recent M5 break of minor structure downward
- M1 pullback into the M5 continuation zone
- M1 buy-side sweep, rejection, bearish BOS, displacement, and volume confirmation

This lets the bot participate in clean continuation sells without chasing price
while it is still far below the original M15 supply zone.
If the M15 retest zone is far away, the M1 continuation layer can show a nearer
local pullback zone, but execution still requires the M1 sweep/rejection/BOS and
volume checks.

## Second AI / Groq

Scan summaries still use the second analyzer's local SMC score. Groq is only
called on near-valid candidate setups before execution.

```json
"external_analyzer_enabled": true,
"external_analyzer_use_groq": true,
"external_analyzer_groq_min_interval_minutes": 5
```

Set `GROQ_API_KEY` in your environment. Keep API keys out of source-controlled
files. If Groq is required and fails on a final candidate, the bot blocks
execution instead of falling back silently.

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
