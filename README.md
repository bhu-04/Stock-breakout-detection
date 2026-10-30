# AI-Based Detection of Stock Breakout Opportunities

Breakout probability estimation from OHLCV market data. **One dashboard, two markets:
India (NSE, INR, Asia/Kolkata - the default) and the United States (USD, America/New_York)**,
each with its own editable watchlist, using delayed Yahoo Finance data: features → XGBoost (+ 3 comparison models) → calibrated probability
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
| `MARKET` | `IN` | The **default** market (what a first-time visitor sees; also used by training/backtest). Both markets are always served |
| `EXCHANGE` | `NSE` | India only: `NSE` or `BSE`. Bare symbols get `.NS` / `.BO` |
| `MARKET_DATA_PROVIDER` | `yfinance` | `yfinance` (both markets), `demo`, or (US only) `alphavantage` / `alpaca` |
| `WATCHLIST` | 10 NSE large caps | **India default list.** Comma-separated; suffix optional |
| `WATCHLIST_US` | 10 US large caps | **US default list** |
| `WATCHLIST_STORE_PATH` | `backend/user_data/watchlists.json` | Where users' add/remove edits are saved. **Use a persistent disk on hosts with an ephemeral filesystem** |
| `MAX_WATCHLIST_SIZE` | `50` | Per market |
| `WATCHLIST_READONLY` | `false` | `true` disables add/remove/reset (403) - recommended for a public deployment |
| `MIN_HISTORY_CANDLES` | `60` | A new symbol needs this many candles to be accepted |
| `MAX_FETCH_CONCURRENCY` | `4` | Parallel provider requests per refresh |
| `MARKET_HOLIDAYS_IN` | empty | NSE/BSE holidays (ISO dates) from the official circular. No India calendar is bundled |
| `MARKET_HOLIDAYS_US` | empty | Ad-hoc NYSE closures only; regular holidays and 13:00 early closes are computed |
| `YFINANCE_CACHE_TTL_SECONDS` | `30` | Per-symbol candle cache; limits Yahoo request rate |
| `ALPHAVANTAGE_API_KEY`, `ALPACA_API_KEY`, `ALPACA_API_SECRET` | empty | Only for `MARKET=US` |

Frontend: `VITE_API_BASE_URL` is read **at build time** (see `frontend/.env.example`).

## Using the dashboard
- **Switch market:** header dropdown (*India - NSE* / *United States - US equities*). Everything - watchlist,
  prices (₹ / $), time zone, session status - follows it. The last choice is remembered in this browser only.
- **Add a stock:** `+ Add Stock`, type a symbol (India: `WIPRO` or `WIPRO.NS`; US: `NFLX`), `Add`. The backend
  checks the symbol against the data provider first. *Invalid / unknown* symbols are refused with a reason;
  if the provider can't be reached you get a distinct "could not verify, nothing was added" message.
- **Remove a stock:** the `×` at the end of its row (works for defaults too).
- **Restore defaults:** `Restore Default Watchlist` resets only the active market; you are asked to confirm
  when it would discard stocks you added.
- **Persistence:** watchlists are stored by the **backend** (`WATCHLIST_STORE_PATH`), so they survive browser
  refreshes, other browsers/devices and restarts - provided that file lives on a persistent disk. They are
  shared by everyone using the deployment (there are no user accounts); set `WATCHLIST_READONLY=true` to lock them.

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
- `/api/health`, `/api/opportunities` and `/api/stock/{symbol}` take `?market=IN|US` (default: `MARKET`) and
  return `market_info` (market, exchange, currency, timezone, session). Unknown markets are a 400. Each market
  has its own provider instance and cache, so one market's data can never answer for the other.
- **US session:** 09:30-16:00 America/New_York (daylight saving handled by IANA data), with NYSE full-day
  holidays and 13:00 early closes computed in `backend/config/calendars.py` (rules-based; add surprise closures
  via `MARKET_HOLIDAYS_US`).
- **API:** `GET /api/markets`, `GET/POST /api/watchlist`, `DELETE /api/watchlist/{symbol}?market=`,
  `POST /api/watchlist/reset`. Writes always require an explicit `market`.
- `/api/health.config_warnings` flags a stale `WATCHLIST` (e.g. old US tickers) or `CURRENCY_SYMBOL`.

## Running tests
```bash
python -m pytest backend/tests -v      # backend (no network; Yahoo is mocked)
cd frontend && npm test && npm run build   # node:test unit tests + Vitest UI tests
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
- Alpha Vantage / Alpaca integrations are untested without real keys and are US-only. The Alpaca provider now
  follows watchlist edits (subscribes/unsubscribes), but that path has only been unit-tested without a socket.
- The model is not market-specific: it is the same demo-trained model for India and the US (see below).
- The shared watchlist file has no authentication; anyone who can reach the API can edit it unless
  `WATCHLIST_READONLY=true`.
- **The shipped model was trained on synthetic demo data** (champion ROC-AUC ~0.47, i.e. near random) and 8 of
  its 19 features are in absolute price units (`sma_*`, `ema_*`, `macd*`, `atr_14`). Probabilities on real NSE
  prices are therefore not meaningful until the model is retrained on real Indian history, ideally with
  price-normalised features.
- Live Yahoo access has not been verified from the development sandbox (network blocked); check
  `/api/opportunities` once on your deployment.
- No news sentiment, deep-learning (LSTM/Transformer), market-regime
  detection, adaptive retraining, or SHAP explainability — listed as
  future scope in `PROJECT_SPEC.md`, intentionally out of MVP scope.
