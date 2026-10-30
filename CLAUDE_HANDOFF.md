# PROJECT HANDOFF

## Project
AI-Based Detection of Stock Breakout Opportunities Using Live Market Streams

## Current Status
MVP complete and working end-to-end on demo data: backend pipeline
(data -> features -> labels -> train -> calibrate -> infer -> rank ->
API) and a React/Tailwind dashboard consuming it. All 4 model types
trained and compared. 19/19 backend tests passing. Backtesting module
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
Added `YFinanceProvider` (backend/data/providers.py) for Indian-market
(NSE/BSE) support, since Alpaca and AlphaVantage don't cover Indian
exchanges:
- Backed by the `yfinance` package (unofficial Yahoo Finance wrapper) —
  no API key, no broker account needed. Fetches on each call (no WS/push;
  Yahoo doesn't offer one), which fits the existing polling dashboard fine.
- Auto-qualifies bare symbols with `.NS` (configurable via
  `YFINANCE_EXCHANGE_SUFFIX`) so a watchlist of `RELIANCE,TCS,INFY,...`
  works without manually typing `.NS` everywhere; symbols that already
  have a dot (e.g. `TCS.NS`, `AAPL` intentionally left as-is... actually
  note: bare US tickers like `AAPL` WILL get `.NS` appended too under this
  provider, since "has a dot" is the only signal — don't mix US and Indian
  tickers in one yfinance watchlist).
- `data_status` is hardcoded to `"delayed"`, never `"live"` — Yahoo data
  has no real-time guarantee (commonly ~15min lag for NSE/BSE). Verified
  the failure path is honest: with Yahoo unreachable (blocked in this
  sandbox), it raises `ProviderUnavailableError` cleanly rather than
  crashing or fabricating candles — reuses all the existing per-symbol
  error handling from the Alpaca work, no pipeline changes needed.
- Added `settings.currency_symbol` (default `"$"`), returned via
  `/api/health`. Removed the two hardcoded `$` in the frontend
  (`OpportunityTable.jsx`, `StockDetail.jsx`) — both now take a
  `currencySymbol` prop sourced from `health.currency_symbol`. Also fixed
  `StockDetail`'s LIVE/DEMO badge to use the real `data_status` field
  instead of the old binary `is_live_data` check (was stale from an
  earlier session).
- `.env.example` documents a ready-to-uncomment Indian-market block
  (`MARKET_DATA_PROVIDER=yfinance`, NSE watchlist, `CURRENCY_SYMBOL=₹`).
- 19/19 backend tests pass, frontend build succeeds. Model, feature
  engineering, ranking, demo provider: untouched, no retraining.

## NEXT TASK
1. On a machine where Yahoo Finance is reachable, set
   `MARKET_DATA_PROVIDER=yfinance`, `WATCHLIST=RELIANCE,TCS,INFY,HDFCBANK,...`,
   `CURRENCY_SYMBOL=₹` in backend/.env and confirm `/api/opportunities`
   returns real NSE candles with `data_status: "delayed"`.
2. NOT implemented: NSE market-hours awareness (9:15–15:30 IST) — the
   system will just show whatever yfinance returns (which itself goes
   stale/flat outside NSE hours); no explicit "market closed" label exists
   yet for this provider, unlike the Alpaca IEX path.
3. Write README.md (still not created).
4. Visually verify the dashboard in a real browser.

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

## Session: India-by-default fix
Root cause of the US display: Indian support was opt-in via the gitignored `backend/.env`, while the
code defaults were `MARKET_DATA_PROVIDER=demo`, a US WATCHLIST and `$`. A deployed backend has no `.env`,
so it always ran those defaults. `YFinanceProvider._qualify` also passed US bare tickers through unsuffixed.
Changes: new `backend/config/market.py` (market specs, symbol qualification, session logic); India/NSE/yfinance
defaults in `settings.py`; `get_provider()` refuses US-only providers for India and no longer treats unknown
names as demo; yfinance candles normalised (tz, NaN rows, duplicates) + TTL cache keyed by market/exchange/
symbol/interval/period; `market_info` on API responses; frontend INR/IST formatting (`src/lib/format.js`).
Not done / open: model retraining on real Indian data (see README limitations); official holiday calendar
(supply via `MARKET_HOLIDAYS`); live Yahoo verification; no deployment config exists in the repo.


## Session: multi-market dashboard (India + US) with editable watchlists
- One backend serves IN and US. `?market=` on /api/health, /opportunities, /stock; new /api/markets and
  /api/watchlist (GET/POST), DELETE /api/watchlist/{symbol}, POST /api/watchlist/reset.
- `config/market.py`: US default list, labels, example symbols, calendar-aware `session_status`
  (US holidays/early closes from `config/calendars.py`). `settings.py`: `default_watchlist(code)`,
  `exchange_for(code)`, `holidays_for(code)`, store/limit options. `MARKET` is now only the DEFAULT market.
- `data/watchlist_store.py` (JSON file, stores only user deltas vs defaults) is wired in. Providers are created
  per market (`api/main._providers`); `SymbolNotFoundError` separates "unknown symbol" (422) from provider
  outage (503) when adding; Alpaca gained `sync_symbols`. Inference runs on a thread pool, one bad symbol
  can't break a cycle.
- Frontend: header market dropdown, `+ Add Stock`, per-row remove, Restore Default Watchlist (confirm when it
  would discard added stocks). Data is tagged with its market and shown only while that market is selected.
  Only `lib/prefs.js` touches localStorage (last selected market).
- Tests: backend 145, frontend 15 (`node --test`) + 20 (Vitest/jsdom, `*.spec.jsx`).
- NOT verified: live Yahoo access for either market (sandbox network blocked); Alpaca socket path;
  the model is still demo-trained and not market-specific.
