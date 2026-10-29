# AI-Based Detection of Stock Breakout Opportunities

Breakout probability estimation from OHLCV market data. **Defaults to the
Indian market (NSE, INR, Asia/Kolkata)** using delayed Yahoo Finance data: features → XGBoost (+ 3 comparison models) → calibrated probability
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
The defaults are baked into `backend/config/settings.py`, so **no `.env` is needed to get India/NSE**.
`backend/.env` is gitignored: a deployed backend does not see your local copy, so on a host set these
as platform environment variables instead.

| Variable | Default | Purpose |
|---|---|---|
| `MARKET` | `IN` | `IN` (India) or `US` |
| `EXCHANGE` | `NSE` | `NSE` or `BSE` (India). Bare symbols get `.NS` / `.BO` |
| `MARKET_DATA_PROVIDER` | `yfinance` | `yfinance`, `demo`, or (US only) `alphavantage` / `alpaca` |
| `WATCHLIST` | 10 NSE large caps | Comma-separated; suffix optional. Foreign suffixes (`BRK.B`, `.L`) are rejected |
| `MARKET_HOLIDAYS` | empty | ISO dates from the official exchange circular. No holiday calendar is bundled |
| `YFINANCE_CACHE_TTL_SECONDS` | `30` | Per-symbol candle cache; limits Yahoo request rate |
| `ALPHAVANTAGE_API_KEY`, `ALPACA_API_KEY`, `ALPACA_API_SECRET` | empty | Only for `MARKET=US` |

Frontend: `VITE_API_BASE_URL` is read **at build time** (see `frontend/.env.example`).

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

## Data sources and honesty
- **India (default):** `yfinance` pulls 5-minute candles from Yahoo Finance. It is an unofficial wrapper
  (no SLA, can rate-limit or break) and NSE/BSE data is **delayed**; the UI shows `DELAYED`, never `LIVE`.
  There is no WebSocket feed for it - the dashboard polls every 15 s.
- A symbol Yahoo has no data for is shown as **unavailable**. It is never replaced by another symbol,
  US data, or demo data. Unknown/US-only provider settings for India yield `DATA UNAVAILABLE`, not demo.
- **Demo mode** (`MARKET_DATA_PROVIDER=demo`) is simulated, labelled `DEMO DATA`, and only used when asked for.
- **Session:** NSE/BSE regular hours 09:15-15:30 IST, Mon-Fri. "Market open" means inside those hours on a
  weekday not listed in `MARKET_HOLIDAYS`; it is not a confirmation that the exchange is trading.
- `/api/health`, `/api/opportunities` and `/api/stock/{symbol}` return `market_info`
  (market, exchange, currency, timezone, session). An explicit `?market=US` on an India deployment is a 400.
- `/api/health.config_warnings` flags a stale `WATCHLIST` (e.g. old US tickers) or `CURRENCY_SYMBOL`.

## Running tests
```bash
python -m pytest backend/tests -v      # backend (no network; Yahoo is mocked)
cd frontend && npm test && npm run build
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
- Alpha Vantage / Alpaca integrations are untested without real keys and are US-only.
- **The shipped model was trained on synthetic demo data** (champion ROC-AUC ~0.47, i.e. near random) and 8 of
  its 19 features are in absolute price units (`sma_*`, `ema_*`, `macd*`, `atr_14`). Probabilities on real NSE
  prices are therefore not meaningful until the model is retrained on real Indian history, ideally with
  price-normalised features.
- Live Yahoo access has not been verified from the development sandbox (network blocked); check
  `/api/opportunities` once on your deployment.
- No news sentiment, deep-learning (LSTM/Transformer), market-regime
  detection, adaptive retraining, or SHAP explainability — listed as
  future scope in `PROJECT_SPEC.md`, intentionally out of MVP scope.
