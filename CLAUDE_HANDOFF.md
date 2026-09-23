# PROJECT HANDOFF

## Project
AI-Based Detection of Stock Breakout Opportunities Using Live Market Streams

## Current Status
MVP complete and working end-to-end on demo data: backend pipeline
(data -> features -> labels -> train -> calibrate -> infer -> rank ->
API) and a React/Tailwind dashboard consuming it. All 4 model types
trained and compared. 17/17 backend tests passing. Backtesting module
implemented with an honest (non-compounded) return calculation.

## Working Features
- Demo OHLCV data generator (regime-switching random walk), per-symbol deterministic
- 19-feature engineering pipeline, shared by training + inference, leakage-tested
- Breakout label construction (price + volume confirmation, configurable N/delta)
- Training pipeline for XGBoost, LightGBM, Random Forest, Logistic Regression
- Probability calibration (sigmoid, fit on held-out validation split)
- Model persistence (`model_store/*.joblib` + `*_latest.json` pointers + `champion.json`)
- Live inference pipeline (single shared feature function, no train/infer mismatch)
- Opportunity ranking (sorted by probability, alert flag at threshold)
- Backtesting: false breakout rate, detection lead time, avg per-trade return,
  max drawdown, Sharpe — explicitly separated from classification metrics
- FastAPI: /api/health, /api/opportunities, /api/stock/{symbol}, /api/model/info,
  /api/models, /api/train, /api/backtest, /api/config
- React dashboard: header (live/demo indicator), summary cards, ranked/sortable/
  filterable opportunity table, candlestick+volume chart (custom Recharts component)
  with resistance/confirmation lines, indicator panel, model info panel, system
  status panel, 15s auto-refresh polling
- Backend test suite (`backend/tests/`): features, labeling (incl. no-lookahead
  check), ranking, inference, API endpoints

## Incomplete Features
- `AlpacaProvider` (real live IEX feed) added but UNTESTED against valid
  credentials in this environment — code path exists, confirmed to reach
  Alpaca's real REST API and correctly report `data_status="unavailable"`
  on bad/missing creds (never falls back to demo silently)
- `AlphaVantageProvider` implemented, honest delayed-vs-live labeling, still
  UNTESTED against a real API key
- Frontend has no automated tests (no component/e2e tests written)
- No SHAP/explainability, no LSTM, no regime detection, no adaptive retraining
  (explicitly out of scope for MVP per PROJECT_SPEC.md)
- Dashboard's "stale data" state is not explicitly implemented (health check
  exists but UI doesn't yet flag "data hasn't updated in X minutes")
- No Docker/deployment config (intentionally — not required for a student project MVP)

## Current Architecture
```
backend/
  config/settings.py       - all tunables (env-overridable)
  data/providers.py        - MarketDataProvider ABC, DemoDataProvider, AlphaVantageProvider
  features/engineering.py  - build_features() — shared training/inference path
  training/labeling.py     - build_labels() — forward-looking, training-only
  training/train.py        - CLI: python -m backend.training.train --model {name|all}
  models/registry.py       - load_model(), list_available_models()
  inference/pipeline.py    - run_inference_cycle() per-symbol
  ranking/rank.py          - rank_opportunities()
  backtesting/backtest.py  - run_backtest()
  api/main.py               - FastAPI app, all endpoints
  model_store/              - trained artifacts (*.joblib, *_latest.json, champion.json)
  tests/                     - pytest suite

frontend/
  src/lib/api.js            - fetch wrapper, base URL from VITE_API_BASE_URL
  src/components/           - Header, SummaryCards, OpportunityTable,
                               CandlestickChart, StockDetail, ModelInfoPanel,
                               SystemStatusPanel
  src/App.jsx                - polling loop (15s), wires everything together
```

## Technology Stack
Backend: Python 3.12, FastAPI, uvicorn, pandas, numpy, scikit-learn,
xgboost, lightgbm, joblib, pydantic-settings, pytest.
Frontend: React 19 (Vite scaffold), Tailwind CSS 3, Recharts.

## Environment Variables (backend/.env, see .env.example)
- MARKET_DATA_PROVIDER — "demo" (default) or "alphavantage"
- ALPHAVANTAGE_API_KEY — required only if provider=alphavantage
- WATCHLIST — comma-separated tickers
- REFRESH_INTERVAL_SECONDS — informational; actual polling interval is set
  in frontend/src/App.jsx (`REFRESH_MS`)

Frontend: frontend/.env → VITE_API_BASE_URL (defaults to http://localhost:8000)

## Commands
```bash
# Backend setup
cd backend && pip install -r requirements.txt --break-system-packages
cp .env.example .env

# Train (required before inference works)
python -m backend.training.train --model xgboost      # single model
python -m backend.training.train --model all          # all 4, sets champion

# Run API
python -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000

# Run tests
python -m pytest backend/tests -v

# Backtest (via API, once trained)
curl http://localhost:8000/api/backtest

# Frontend
cd frontend && npm install
npm run dev      # dev server on :5173
npm run build    # production build (verified working)
```

## Model Status
- Trained: xgboost, lightgbm, random_forest, logistic_regression (all on
  demo data, 1200 candles/symbol across the 10-symbol watchlist)
- Champion: lightgbm (highest ROC-AUC among the four, ~0.466 — near-random,
  as expected: demo data is a synthetic random walk with no persistent
  exploitable edge, so this is the HONEST result, not a bug)
- Feature list: `backend/features/engineering.py::FEATURE_COLUMNS` (19 features)
- Artifacts: `backend/model_store/*.joblib`

## Data Status
- Live provider: AlphaVantageProvider implemented, untested (no key configured)
- Demo provider: DemoDataProvider, default, always available, clearly labeled
- Expected schema: timestamp, open, high, low, close, volume (ascending by time)
- Limitation: demo data has no genuine multi-day pattern memory — it's a
  regime-switching GBM-style walk, good enough for pipeline demonstration,
  not for claiming realistic backtested trading performance

## Known Bugs
- None currently open. (Fixed during this session: backtest equity curve
  was naively compounding overlapping/correlated signals via cumprod,
  producing an unrealistic ~899% "return" — changed to averaged,
  non-compounded per-trade returns; see backend/backtesting/backtest.py
  docstring for the full explanation.)
- Background processes (uvicorn/vite) in this sandboxed dev environment
  sometimes die between tool calls — not a code bug, just a container
  process-lifecycle quirk. Use `setsid ... &` and re-check `ps aux` if a
  server appears to have stopped responding.

## Decisions Made
- Demo data generator uses per-symbol seeded RNG for reproducibility in
  training, but `get_latest_candle()` advances the walk statefully to
  simulate a live feed for repeated polling.
- Resistance is computed with `shift(1)` so a candle's own high never
  leaks into its own resistance/feature calculation (see
  `test_resistance_excludes_current_bar`).
- Backtest strategy returns are NOT compounded across overlapping signals
  (see Known Bugs above) — this was a deliberate fix for honesty, not the
  original design.
- Champion model selection is purely "highest ROC-AUC among trained
  models" — simple and transparent, recorded in `model_store/champion.json`.

## Last Completed Task (this session)
Added a genuine live provider, `AlpacaProvider` (backend/data/providers.py):
- REST seed (`GET /v2/stocks/bars`, feed=iex) warms up `alpaca_seed_bar_limit`
  (default 300) historical 1-min bars per watchlist symbol before anything
  goes live, so RSI/MACD/ATR/etc. are never computed on a cold buffer.
- A background daemon thread opens `wss://stream.data.alpaca.markets/v2/iex`,
  authenticates, subscribes to the `bars` channel for the watchlist, and
  appends/replaces bars into a lock-protected per-symbol DataFrame buffer.
  Auto-reconnects with exponential backoff on drops; does NOT retry on an
  auth rejection (treated as permanently unavailable until creds change).
- `data_status` is a property: "unavailable" (bad/missing creds, or REST
  seed totally failed), "delayed" (seeded but WS not yet authenticated),
  "live" (WS authenticated + subscribed). `feed` is always "iex" and is
  surfaced end-to-end so the UI shows "LIVE • IEX", never implying
  full-market coverage.
- `get_provider()`: Alpaca is treated as a deliberate LIVE choice — if
  `ALPACA_API_KEY`/`ALPACA_API_SECRET` are missing, returns a new
  `_UnavailableProvider` stub (`data_status="unavailable"`, every read
  raises `ProviderUnavailableError`) instead of the old Alpha-Vantage-style
  silent-fallback-to-demo behavior. Verified live against Alpaca's real API
  (got a genuine 403 with bad test creds, correctly classified as
  "unavailable" with a clear error message, no crash, no silent demo swap).
- Existing per-symbol `ProviderUnavailableError` handling in
  `inference/pipeline.py` (added last session) required NO changes — Alpaca
  reuses it automatically.
- API responses (`/api/health`, `/api/opportunities`, `/api/stock/{symbol}`)
  now also return `data_feed`.
- Frontend `Header`/`SystemStatusPanel` append `• IEX` to the LIVE label
  when a feed is present.
- Model, feature engineering, ranking, demo provider: untouched. No
  retraining performed. 19/19 backend tests still passing, frontend build
  still succeeds.

## NEXT TASK
1. Get real Alpaca paper/live API keys, set `MARKET_DATA_PROVIDER=alpaca` +
   `ALPACA_API_KEY`/`ALPACA_API_SECRET` in backend/.env, start uvicorn, and
   confirm within a few seconds `/api/health` reports `data_status: "live"`,
   `data_feed: "iex"` during market hours (during closed hours it will sit
   at "delayed" — WS authenticates but no new bars arrive until the market
   opens; this is expected, not a bug — consider adding an explicit
   `market_open` flag if that ambiguity matters to the reviewer).
2. Write README.md (still not created).
3. Visually verify the dashboard in a real browser.
4. Consider aggregating Alpaca's fixed 1-min live bars into 5-min candles
   client-side in `_on_bar` if matching the demo data's 5-min granularity
   turns out to matter for the champion model's real-world behavior (not
   done here — out of scope for "don't retrain / minimal change").

## DO NOT CHANGE (additions)
- `AlpacaProvider._ws_run_forever`'s auth-failure branch (`return` instead
  of retrying) — retrying on bad credentials would spam Alpaca's auth
  endpoint and never resolve itself.
- `get_provider()`'s Alpaca branch — must never fall back to
  `DemoDataProvider()` on misconfiguration; that's the one thing this
  session was explicitly asked to fix.

## DO NOT CHANGE
- `backend/features/engineering.py::build_features` — the shared
  training/inference contract; changing its signature or leakage
  guarantees (shift-based windows) requires re-validating
  `test_no_lookahead_in_features` and retraining every model.
- `backend/training/labeling.py::build_labels` — deliberately kept
  separate from `build_features` so inference code can never accidentally
  call a function that looks at future candles.
- The backtest's non-compounded return calculation (see Known Bugs) —
  reverting to `np.cumprod` reintroduces the overlapping-signal
  overstatement bug.

## Resume Instructions
A new Claude instance should read this file + PROJECT_SPEC.md + README.md,
then run `python -m pytest backend/tests -v` to confirm the repo is still
in a working state before making changes.