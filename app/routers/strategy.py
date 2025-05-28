from fastapi import APIRouter, HTTPException
import time
import numpy as np
import pandas as pd
from datetime import timedelta
from app.config import logger, settings
from app.models import StrategyInput, StrategyExecuteInput, BacktestInput
from app.utils.data_processing import build_strategy_legs
from app.utils.upstox_helpers import place_order_for_leg, fetch_trade_pnl
from app.routers.market_data import ComprehensiveOptionChainFetcher

router = APIRouter()

@router.post("/strategy/suggest", summary="Suggests option strategies based on market metrics")
def suggest_strategy(data: StrategyInput):
    """
    Suggests suitable option trading strategies based on provided market metrics
    such as IVP, VIX, PCR, straddle price, event impact, ATM IV, realized volatility, and IV skew.
    """
    try:
        iv_rv = data.atm_iv / data.realized_vol if data.realized_vol else 0

        # Refined regime classification
        regime = "Neutral"
        if data.ivp > 60 and data.vix > 18:
            regime = "High Volatility Expansion" # Typically favors short straddles/strangles if mean-reversion expected
        elif data.ivp < 30 and data.vix < 12:
            regime = "Low Volatility Contraction" # Typically favors long straddles/strangles for breakout
        elif data.pcr > 1.2 or data.pcr < 0.8:
            regime = "Extreme Sentiment" # Could imply reversal or continuation
        elif data.iv_skew_slope > 0.5:
            regime = "Bearish Skew" # Puts expensive, implies downside concern

        strategies = []

        # Adapt suggestions based on refined regimes or direct conditions
        if regime == "High Volatility Expansion":
            strategies.append({"name": "Short Straddle / Strangle (for IV mean reversion)", "confidence": 0.8, "max_loss_estimate": 5000})
        elif regime == "Low Volatility Contraction":
            strategies.append({"name": "Long Straddle / Strangle (for breakout)", "confidence": 0.7, "max_loss_estimate": 4000})

        if data.pcr > 1.2: # Bullish sentiment from PCR
            strategies.append({"name": "Bull Put Spread", "confidence": 0.6, "max_loss_estimate": 3000})
        elif data.pcr < 0.8: # Bearish sentiment from PCR
            strategies.append({"name": "Bear Call Spread", "confidence": 0.6, "max_loss_estimate": 3000})

        if data.ivp >= 50 and data.vix > 13.5 and data.straddle_price >= 150:
             strategies.append({"name": "Iron Fly (for range-bound with high IV)", "confidence": 0.75, "max_loss_estimate": 5000})
        elif data.vix < 12 and 0.9 <= data.pcr <= 1.1:
            strategies.append({"name": "Short Strangle (for low volatility, sideways)", "confidence": 0.7, "max_loss_estimate": 3500})

        if not strategies:
            strategies.append({"name": "No clear strategy suggested by current metrics. Exercise caution.", "confidence": 0, "max_loss_estimate": 0})

        return {
            "regime": regime,
            "suggested_strategies": strategies
        }
    except Exception as e:
        logger.error(f"Strategy suggestion error: {e}")
        raise HTTPException(status_code=500, detail=f"Strategy suggestion error: {str(e)}")

@router.post("/strategy/execute", summary="Executes a defined option strategy")
async def execute_strategy(data: StrategyExecuteInput):
    """
    Executes a predefined option strategy (Iron Fly, Iron Condor, Bull Put Spread, Bear Call Spread)
    via the Upstox API. This involves placing multiple individual orders.
    """
    try:
        quantity = int(float(data.quantity))
        fetcher = ComprehensiveOptionChainFetcher(data.access_token)
        raw_option_chain_data = data.option_chain.get('data', [])
        _, _, combined_df, _, _ = fetcher.parse_comprehensive_option_data(raw_option_chain_data)
        if combined_df.empty:
            raise HTTPException(status_code=400, detail="Empty option chain data.")
        
        legs = build_strategy_legs(combined_df, data.spot_price, data.strategy_name, quantity, data.otm_distance)
        if not legs:
            raise HTTPException(status_code=400, detail=f"No valid legs could be built for {data.strategy_name}.")

        estimated_entry_premium = 0
        for leg in legs:
            if leg['action'] == 'SELL':
                estimated_entry_premium += (leg['ltp'] * leg['quantity'])
            else:
                estimated_entry_premium -= (leg['ltp'] * leg['quantity'])

        estimated_max_loss_placeholder = 0
        if data.strategy_name.lower() == "iron_fly":
            estimated_max_loss_placeholder = (data.otm_distance * 2 * quantity) * 0.5
        elif data.strategy_name.lower() == "iron_condor":
            estimated_max_loss_placeholder = (data.otm_distance * quantity) * 0.5
        elif "spread" in data.strategy_name.lower():
            estimated_max_loss_placeholder = (data.otm_distance * quantity) * 0.5

        order_results = []
        total_pnl_realized = 0
        for leg in legs:
            result = await place_order_for_leg(data.access_token, leg)
            if result and result.get('order_id'):
                order_results.append(result)
                order_id = result['order_id']
                time.sleep(2)
                pnl = await fetch_trade_pnl(data.access_token, order_id)
                total_pnl_realized += pnl
            else:
                logger.error(f"Order placement failed for leg: {leg}. Result: {result}")

        return {
            "order_results": order_results,
            "trade_pnl_simulation": total_pnl_realized,
            "estimated_entry_premium": estimated_entry_premium,
            "estimated_max_loss": estimated_max_loss_placeholder,
            "legs_attempted": legs,
            "option_chain_data": combined_df.to_dict(orient='records')
        }
    except Exception as e:
        logger.error(f"Strategy execution error: {e}")
        raise HTTPException(status_code=500, detail=f"Strategy execution error: {str(e)}")

@router.post("/backtest", summary="Backtests a given option strategy over a historical period (Simulated)")
def backtest_strategy(data: BacktestInput):
    """
    Performs a simulated backtest of a given option strategy over historical Nifty data.
    NOTE: This is a simplified simulation and does not use real historical option chain data.
    Option prices are approximated based on spot and random extrinsic value.
    """
    try:
        df = pd.read_csv(settings.NIFTY_HISTORICAL_DATA_URL)
        df.columns = df.columns.str.strip()
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce", format="%d-%b-%Y")
        df = df.dropna(subset=["Date"]).set_index("Date").sort_index()
        if 'Close' not in df.columns:
            raise ValueError(f"CSV file does not contain 'Close' column")

        end_date = df.index[-1]
        start_date = end_date - timedelta(days=data.period)
        df_backtest = df.loc[start_date:end_date]

        if df_backtest.empty or len(df_backtest) < 2:
            raise HTTPException(status_code=400, detail="Not enough data for the specified backtesting period.")

        quantity = int(float(data.quantity))
        np.random.seed(42) # For reproducibility

        trades_history = []
        for i in range(len(df_backtest) - 1):
            current_date = df_backtest.index[i]
            spot = df_backtest['Close'].iloc[i]
            next_spot = df_backtest['Close'].iloc[i + 1] # Next day's close for P&L calculation

            # Simulate option chain for the current day
            atm_strike = round(spot / 50) * 50
            simulated_strikes = sorted(list(set([
                atm_strike - 200, atm_strike - 150, atm_strike - 100, atm_strike - 50,
                atm_strike,
                atm_strike + 50, atm_strike + 100, atm_strike + 150, atm_strike + 200
            ])))

            mock_chain_data = []
            for s in simulated_strikes:
                ce_intrinsic = max(0, spot - s)
                pe_intrinsic = max(0, s - spot)

                # Simulate extrinsic value (more for ATM, less for OTM)
                ce_extrinsic = np.random.uniform(5, 25) if abs(s - spot) < 100 else np.random.uniform(1, 10)
                pe_extrinsic = np.random.uniform(5, 25) if abs(s - spot) < 100 else np.random.uniform(1, 10)

                mock_chain_data.append({
                    "strike_price": s,
                    "call_options": {
                        "instrument_key": f"NSE_FO|NIFTY|{current_date.strftime('%Y%m%d')}CE{s}",
                        "market_data": {"ltp": ce_intrinsic + ce_extrinsic}
                    },
                    "put_options": {
                        "instrument_key": f"NSE_FO|NIFTY|{current_date.strftime('%Y%m%d')}PE{s}",
                        "market_data": {"ltp": pe_intrinsic + pe_extrinsic}
                    }
                })

            legs_to_execute = build_strategy_legs(mock_chain_data, spot, data.strategy_name, quantity, otm_distance=50)

            daily_pnl = 0
            for leg in legs_to_execute:
                strike = leg['strike']
                opt_type = 'call_options' if 'CE' in leg['instrument_key'] else 'put_options'

                entry_ltp_for_leg = 0.0
                for mc_item in mock_chain_data:
                    if mc_item.get('strike_price') == strike and opt_type in mc_item:
                        entry_ltp_for_leg = mc_item[opt_type].get('market_data', {}).get('ltp', 0.0) or 0.0
                        break

                intrinsic_at_exit = max(0, next_spot - strike) if 'CE' in leg['instrument_key'] else max(0, strike - next_spot)
                # Simulate a decrease in extrinsic value (time decay + random noise)
                simulated_exit_ltp_for_leg = intrinsic_at_exit + (np.random.uniform(0.1, 0.5) * (entry_ltp_for_leg - intrinsic_at_exit))
                simulated_exit_ltp_for_leg = max(0.01, simulated_exit_ltp_for_leg) # LTP cannot be negative

                if leg['action'] == 'SELL':
                    daily_pnl += (entry_ltp_for_leg - simulated_exit_ltp_for_leg) * leg['quantity']
                else: # BUY
                    daily_pnl += (simulated_exit_ltp_for_leg - entry_ltp_for_leg) * leg['quantity']

            trades_history.append({"date": current_date.strftime("%Y-%m-%d"), "pnl": daily_pnl})

        total_pnl = sum(t["pnl"] for t in trades_history)
        win_rate = sum(1 for t in trades_history if t["pnl"] > 0) / len(trades_history) if trades_history else 0

        max_drawdown = 0
        running_pnl = 0
        peak_pnl = 0
        for trade in trades_history:
            running_pnl += trade["pnl"]
            if running_pnl > peak_pnl:
                peak_pnl = running_pnl
            drawdown = peak_pnl - running_pnl
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return {
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 2),
            "avg_pnl_per_trade": round(total_pnl / len(trades_history), 2) if trades_history else 0,
            "max_drawdown": round(max_drawdown, 2),
            "pnl_history": trades_history
        }
    except Exception as e:
        logger.error(f"Backtest error: {e}")
        raise HTTPException(status_code=500, detail=f"Backtest error: {str(e)}")
