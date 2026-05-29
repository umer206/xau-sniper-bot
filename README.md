# XAU Sniper Bot

Multi-timeframe MT5 scanner for Gold setups:

- H1: directional bias
- M15: setup zone
- M5: confirmation after zone interaction
- M1: sniper trigger timing
- OpenAI: final validation only after zone interaction, M5 confirmation, and a near-valid M1 trigger

The bot is dry-run by default. It prints signals to the console and writes JSONL signal records locally.

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
