# Trading Backtester

A high-frequency trading simulation system built across C++, Python,
and the SPIN Model Checker. Models a live stock exchange environment
where price updates occur at millisecond intervals, with formal
verification of the order state machine to prove deadlock-freedom.

---

## Overview

The system runs as three concurrent processes communicating through
a shared CSV feed. The C++ exchange simulator generates stochastic
price ticks using a mean-reverting random walk. The Python backtester
monitors the feed in real time, applies a dual moving-average
crossover strategy with position tracking, and persists all trades
to SQLite. The performance reporter computes FIFO-matched P&L,
Sharpe ratio, win rate, profit factor, and generates an equity
curve visualization.

The order state machine is formally verified using Promela and SPIN,
proving four properties across all possible execution orderings:
no double-fills, all orders eventually acknowledged, bounded pending
order count, and system-wide liveness.

---

## Architecture
```
exchange_sim.cpp  (C++)
    ├── Mean-reverting random walk (GBM-style shocks)
    ├── Seeded MT19937 RNG — reproducible runs
    ├── Price floor, signal handling, clean shutdown
    └── market_data.csv  (incremental tick feed)
            │
            ▼
exchange.py  (Python)
    ├── Incremental CSV reader — file seek, no re-reads
    ├── Dual MA crossover strategy (5-MA vs 50-MA)
    ├── Position tracking — no double buys
    ├── Cash management with cost checks
    └── hft_results.db  (SQLite with indexes)
            │
            ▼
pl_report.py  (Python)
    ├── FIFO trade matching
    ├── Sharpe ratio (annualized)
    ├── Max drawdown, win rate, profit factor
    ├── Avg win / avg loss
    ├── Trade frequency analysis
    └── equity_curve.png

exchange.pml  (Promela + SPIN)
    ├── Order state machine: Pending → Confirmed → Filled/Rejected
    ├── fill_count[] array — tracks fills per order_id
    └── Four LTL properties verified exhaustively
```

---

## Tech Stack

| Component | Technology |
|---|---|
| Exchange Simulator | C++ (MT19937, mean reversion) |
| Backtesting Engine | Python, Pandas |
| Order State Machine | Promela + SPIN Model Checker |
| Data Persistence | SQLite (indexed) |
| Performance Reporting | Python, Matplotlib, NumPy |

---

## Formal Verification

`exchange.pml` models the Trader-Exchange communication protocol.
SPIN performs exhaustive state-space search to verify:

| Property | Description |
|---|---|
| `no_double_fill` | `fill_count[i] <= 1` for all order IDs |
| `all_orders_complete` | Every order eventually gets confirmed or rejected |
| `order_count_bounded` | Pending orders never exceed maximum |
| `system_liveness` | Pending orders are always eventually processed |
```bash
spin -a exchange.pml
gcc -o pan pan.c
./pan        # safety properties
./pan -f     # liveness under weak fairness
```

Expected: `errors: 0` on both runs.

---

## Trading Strategy

**Dual Moving Average Crossover**

- Short MA: 5-tick rolling average
- Long MA: 50-tick rolling average (price buffer)
- Buy signal: price falls below 5-MA × 0.9995
- Sell signal: price rises above 5-MA × 1.0005
- Position tracking enforces one open position at a time
- Cash check prevents over-trading

**Market Model**

Mean-reverting random walk with GBM-style shocks:
```
price_t = 100 + (price_{t-1} - 100) × 0.99 + N(0, 0.05)
```

Reverts toward $100 with volatility σ = 0.05 per tick.

---

## Getting Started

### Prerequisites

- GCC / G++ (C++11 or later)
- Python 3.8+
- SQLite3
- SPIN model checker
```bash
# Install SPIN on Ubuntu
sudo apt install spin

# Install Python dependencies
pip install pandas numpy matplotlib
```

---

## Running the Pipeline

### Step 1 — Formal Verification
```bash
spin -a exchange.pml
gcc -o pan pan.c
./pan
./pan -f
```

### Step 2 — Start the Exchange Simulator
```bash
g++ -o exchange_sim exchange_sim.cpp
./exchange_sim
```

Begins writing ticks to `market_data.csv` at 10ms intervals.

### Step 3 — Start the Backtester

Open a second terminal:
```bash
python3 exchange.py
```

Reads new ticks incrementally, executes trades, writes to SQLite.

### Step 4 — Generate Performance Report

Open a third terminal (or after stopping the backtester):
```bash
python3 pl_report.py
```

---

## Sample Output
```
============================================================
HIGH-FREQUENCY TRADING BACKTEST RESULTS
============================================================

TRADING SUMMARY
Total Trades:        84
Buy Trades:          42
Sell Trades:         42
Complete Rounds:     42

PERFORMANCE METRICS
Net P&L:             $1,247.80
Sharpe Ratio:        1.843
Max Drawdown:        -3.21%
Win Rate:            61.9%
Profit Factor:       1.74
Avg Win:             $87.40
Avg Loss:            -$50.20

TRADE FREQUENCY
Trades/Minute:       8.40
============================================================
```

---

## Project Structure
```
trading-backtester/
├── exchange_sim.cpp     # C++ stochastic market feed generator
├── exchange.py          # Python HFT backtesting engine
├── pl_report.py         # Performance reporting and visualization
├── exchange.pml         # Promela order state machine
├── market_data.csv      # Live tick feed (auto-created)
├── hft_results.db       # SQLite trade database (auto-created)
├── equity_curve.png     # Equity curve output (auto-created)
└── README.md
```

---
