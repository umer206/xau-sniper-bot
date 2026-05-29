# XAU Sniper Bot

Multi-timeframe MT5 scanner for Gold setups:

- H1: directional bias
- M15: setup zone
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

Run continuously:

```powershell
python -m xau_sniper_bot.bot --config config.json
```

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
