# VolGuard Pro Backend API

This is the backend API for VolGuard Pro, an application designed for market data analysis, volatility forecasting, strategy suggestion, and trade execution.

## Features

* **Market Data:** Fetch real-time option chain and market depth from Upstox.
* **Volatility Forecasting:** Predict future volatility using XGBoost and GARCH models.
* **Strategy Suggestion:** Recommend option strategies based on market metrics (IVP, VIX, PCR, Skew, etc.).
* **Risk Management:** Real-time risk checks against predefined loss limits.
* **Trade Execution:** Execute option strategies (Iron Fly, Iron Condor, Spreads) via Upstox API.
* **Trade Logging & Analytics:** Log executed trades and provide performance insights.
* **User Management:** Fetch authenticated user details (profile, funds, holdings, positions, orders).
* **Backtesting (Simulated):** Basic backtesting functionality for strategies.

## Project Structure
