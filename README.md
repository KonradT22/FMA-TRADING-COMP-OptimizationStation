# FMA Quantitative Trading Competition — 1st Place 🏆

A fully automated, event-driven equity trading bot built for the **2026 University of Minnesota Financial Management Association (FMA) Quantitative Trading Competition**. The strategy ran live in the cloud against real-time market data over a 10-day trading window and secured **1st Place** in front of a judging panel of industry professionals from **DRW** and **Cargill**.

---

## Performance

| Metric | Value |
|---|---|
| Live Trading Window | April 9 – April 19, 2026 |
| Account Size | $1,000,000 (paper) |
| Total Return | **+0.70%** (+$7,046.97) |
| Max Drawdown | **0.00%** |
| Per-Trade Return | **+4.70%** |
| Win Rate | **100%** (1 for 1) |
| Trades Executed | 1 (NFLX) |
| Total Value Traded | $306,988 |
| Turnover Ratio | 30.59% |

### A Note on Benchmark & Alpha

The portfolio underperformed the S&P 500 benchmark (+6.97%) during this specific window, but that was by design. The market experienced an aggressive tariff-relief rally over the period. Because our parameters strictly required high-quality, idiosyncratic earnings setups, the bot actively rejected sub-optimal trades and held cash for 8 of the 10 trading days. The result was a **0.00% maximum drawdown** and a clean **+4.7% capture on the single valid signal**.

---

## Architecture

```
AlpacaLiveFeed (IEX 1-min polling)
        │
        ▼
   Engine loop
        │
        ▼
Strategy.on_data()  ──►  signal evaluation
        │
        ▼
Broker.post_order()  ──►  Alpaca REST API
        │
        ▼
Strategy.on_execution()  ──►  fill handling & stop tracking
```

| Component | Technology |
|---|---|
| Language | Python 3.13 |
| Brokerage & Data | Alpaca REST API (IEX 1-min bars) |
| Hosting | DigitalOcean Ubuntu Server |
| Process Management | tmux + Linux cron (daily start/kill) |
| Containerization | Docker |

The system is built around four pluggable abstractions — **Feed**, **Broker**, **Portfolio**, and **Strategy** — making it straightforward to swap between live trading and backtesting without changing strategy code.

---

## Strategy: Post-Earnings Announcement Drift (PEAD)

The algorithm targets structural inefficiencies around high-volatility corporate earnings reports using a two-sleeve approach.

### Sleeve A — Pre-Earnings Momentum

Captures momentum building into an earnings catalyst.

- **Trigger:** Stock reports earnings in 1–3 trading days with a proprietary momentum score ≥ 0.90
- **Conditions:** Price > SMA(20) and Price > Intraday VWAP at 10:15 AM EST
- **Exit:** Hard close at 3:55 PM the day before earnings to eliminate binary overnight event risk

### Sleeve B — Post-Earnings Drift

Captures institutional accumulation following a strong earnings gap-up.

- **Trigger:** Overnight gap of +2.0% to +8.0% following an earnings report
- **Conditions:** Price holds above Intraday VWAP at 10:30 AM EST
- **Exit:** Fixed 2-trading-day hold to capture drift as institutions scale into positions

### Momentum Scoring

Each stock in the universe is assigned a pre-computed event score (0–1) derived from five cross-sectional factors:

| Factor | Weight |
|---|---|
| Fundamental momentum (EPS/revenue trend) | 35% |
| Estimate revision direction | 20% |
| Relative strength vs. SPY | 20% |
| Accumulation days (volume-confirmed up days) | 15% |
| IV attractiveness (options-implied expected move) | 10% |

---

## Risk Management

Risk was enforced at both the position and portfolio level.

**Position-level stops**
- Dynamic stop floor: `Entry Price − (1.5 × ATR₁₄)`, bounded by the morning intraday low
- Designed to absorb normal intraday noise while cutting real adverse moves

**Portfolio-level limits**
- 15% of portfolio equity per position
- Maximum 4 concurrent open positions
- 50% gross exposure cap — at least half the portfolio stays in cash at all times

**Kill switches**
- **Level 1 (−4% drawdown):** Tighten gross exposure cap to 25%, halt new entries
- **Level 2 (−5% drawdown):** Liquidate all positions and halt trading for the session

---

## Infrastructure Challenges & V2.0 Roadmap

Running a live polling engine on a fragmented data feed (IEX) introduced zero-volume minute stalls that could hang the execution loop. We engineered infrastructure-level bypasses using **tmux** and **cron** to automatically reboot the environment on a daily schedule, ensuring uninterrupted operation across the full 10-day window.

**V2.0 improvements:**

- Replace REST polling with an async WebSocket stream (e.g., Polygon.io) for tick-by-tick state management and elimination of stall risk
- Expand the tradable universe from 24 large-caps to the Russell 2000 to capture stronger PEAD anomalies in lower-float equities
- Replace static entry thresholds with IV-adjusted bounds to adapt to changing macroeconomic regimes

---

## Setup

### Prerequisites

- Python 3.13+
- [Alpaca account](https://alpaca.markets/) with API keys (paper or live)
- Docker (optional but recommended)

### Environment Variables

Create an `env.list` file in the project root (this file is gitignored):

```
ALPACA_API_KEY=your_key_here
ALPACA_API_SECRET=your_secret_here
ALPACA_PAPER=true
```

### Run with Docker

```bash
docker build -t systrade .
docker run --env-file env.list -d systrade
docker logs -f $(docker ps -lq)
```

### Run locally

```bash
pip install -e .
export $(cat env.list)
python src/systrade/trading_app.py
```

### Rebuild data files (optional)

The earnings calendar, event scores, and options data are pre-built and committed. To regenerate them:

```bash
python build_datasets.py   # earnings_calendar.csv, options_data.csv
python build_features.py   # estimates.csv
```

### Run tests

```bash
pip install -e ".[test]"
pytest tests/
```

---

## Team

- [Konrad Trestka](https://github.com/KonradT22)
- Chad Chowdhury
- Huy Pham
