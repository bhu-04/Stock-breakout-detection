# AI-Based Detection of Stock Breakout Opportunities

Real-time (demo/live) breakout probability estimation from OHLCV market
data: features → XGBoost (+ 3 comparison models) → calibrated probability
→ ranked opportunities → dashboard.

**This is a research/analytics tool.** Breakout probability is a model
estimate, not a guarantee of future price movement. Demo mode uses
simulated data and is clearly labeled as such throughout the API and UI.

## Architecture

```
backend/   FastAPI + pandas/scikit-learn/xgboost/lightgbm pipeline
frontend/  React (Vite) + Tailwind + Recharts dashboard
```

See `PROJECT_SPEC.md` for the full pipeline spec and `CLAUDE_HANDOFF.md`
for current implementation status.

## Requirements
- Python 3.10+
- Node.js 18+

## Installation

```bash
cd backend
pip install -r requirements.txt --break-system-packages
cp .env.example .env

cd ../frontend
npm install
echo "VITE_API_BASE_URL=http://localhost:8000" > .env
```

## Environment variables (`backend/.env`)
| Variable | Purpose |
|---|---|
| `MARKET_DATA_PROVIDER` | `demo` (default, no key needed) or `alphavantage` |
| `ALPHAVANTAGE_API_KEY` | required only if provider is `alphavantage` |
| `WATCHLIST` | comma-separated tickers to monitor |
| `REFRESH_INTERVAL_SECONDS` | informational; UI polling interval is set in `frontend/src/App.jsx` |

## Running the backend
Run from the **repo root** (not inside `backend/`) so the `backend`
package resolves correctly:
```bash
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000
```

## Running the frontend
```bash
cd frontend
npm run dev
```
Open http://localhost:5173.

## Training models
A model must be trained before `/api/opportunities` or the dashboard will
show real probabilities — otherwise the UI clearly shows "Model
Unavailable" rather than fabricating a number.

```bash
python -m backend.training.train --model xgboost      # single model
python -m backend.training.train --model all          # trains & compares all 4, sets the champion
```
Trained artifacts are saved to `backend/model_store/`.

## Demo mode
Demo mode is the default (`MARKET_DATA_PROVIDER=demo`) and requires no
API key or internet access — it generates realistic-looking synthetic
OHLCV data and runs the complete pipeline. The dashboard shows a "DEMO
DATA" badge whenever demo data is in use.

## Connecting live data
Set `MARKET_DATA_PROVIDER=alphavantage` and `ALPHAVANTAGE_API_KEY` in
`backend/.env`. If the key is missing or invalid, the app automatically
falls back to demo data rather than crashing. Other providers can be
added by implementing the `MarketDataProvider` interface in
`backend/data/providers.py`.

## Running tests
```bash
python -m pytest backend/tests -v
```

## Backtesting
```bash
curl http://localhost:8000/api/backtest
```
Reports MODEL performance (classification metrics) and STRATEGY
performance (false breakout rate, avg per-trade return, drawdown, Sharpe)
**separately** — a model's classification quality does not by itself
imply trading profitability.

## Known limitations
- Demo data is a synthetic regime-switching random walk; it is useful for
  exercising the full pipeline but has no genuine multi-day market
  structure, so trained-model metrics on it are modest (this is reported
  honestly, not inflated).
- Live data support (`AlphaVantageProvider`) is implemented but untested
  without a real API key.
- No news sentiment, deep-learning (LSTM/Transformer), market-regime
  detection, adaptive retraining, or SHAP explainability — listed as
  future scope in `PROJECT_SPEC.md`, intentionally out of MVP scope.
