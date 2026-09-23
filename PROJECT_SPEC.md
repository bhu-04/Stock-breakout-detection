# PROJECT SPEC

## Project
AI-Based Detection of Stock Breakout Opportunities Using Live Market Streams
(Bhuvan Rajesh 23MIA1020, Mithra V 23MIA1093)

## Objective
Estimate P(Breakout within next N candles | X_t) — a probability, not an
exact price prediction.

## Breakout definition
Y_t = 1 if max(high_{t+1..t+N}) > R_t * (1 + delta) AND at least one of the
next N candles has relative volume >= volume_confirmation_multiple, else 0.
- R_t = rolling max high over `resistance_window` candles, EXCLUDING candle t
- delta = `confirmation_threshold_pct`
- N = `prediction_horizon`

All four of these are runtime-configurable via `backend/config/settings.py`
/ `.env` — never hardcoded in pipeline code.

## Pipeline (must stay in this order)
Market Data -> Validation -> OHLCV -> Feature Engineering -> Breakout
Labeling -> Model Training -> Probability Calibration -> Live Inference ->
Opportunity Ranking -> Dashboard

## Feature groups (19 features, `backend/features/engineering.py`)
Price/Returns, Momentum (RSI, MACD), Trend (SMA/EMA/crossover), Volatility
(ATR, BB width, hist. vol), Volume (rel. volume, spike), Price level
(distance from resistance, VWAP deviation). One function
(`build_features`) is shared by training AND inference — no separate
code paths, no train/inference mismatch.

## Models
Primary: XGBoost. Comparison: LightGBM, Random Forest, Logistic
Regression. All four trained via `python -m backend.training.train
--model all`. Class imbalance handled via `scale_pos_weight` /
`class_weight="balanced"`. Probabilities calibrated via sigmoid/Platt
scaling on a held-out validation split.

## Evaluation
Classification: accuracy, precision, recall, F1, ROC-AUC, PR-AUC
(`backend/training/train.py`).
Strategy/backtest (kept separate from classification metrics): false
breakout rate, detection lead time, avg per-trade return, max drawdown,
Sharpe ratio (`backend/backtesting/backtest.py`). Never conflate the two.

## Data
Demo/mock mode (`backend/data/providers.py::DemoDataProvider`) is the
default and always available — regime-switching synthetic random walk,
clearly labeled DEMO/SIMULATED everywhere in the API and UI. Live mode
(`AlphaVantageProvider`) is a swappable adapter behind the same
`MarketDataProvider` interface; the app falls back to demo data if a live
provider is requested but not configured.

## Safety / presentation rules
- Never claim guaranteed outcomes. Use "estimated probability", "model
  signal", "backtested result".
- Demo data is always labeled as such (`is_live_data: false`, "DEMO" badge).
- Never fabricate metrics — an untrained model reports "unavailable", not
  invented numbers.

## Out of scope for MVP (future scope, do not block on these)
News sentiment integration, LSTM/Transformer models, market-regime
detection, adaptive retraining, SHAP-based explainability.
