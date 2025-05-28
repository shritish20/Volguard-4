import pandas as pd
import numpy as np
from datetime import datetime
from app.config import logger

# Global variable for previous OI
prev_oi = {}

def process_chain_data(combined_df: pd.DataFrame):
    """Processes combined_df from ComprehensiveOptionChainFetcher into a structured DataFrame."""
    global prev_oi
    rows = []
    ce_oi_total = combined_df[combined_df['option_type'] == 'CALL']['oi'].sum()
    pe_oi_total = combined_df[combined_df['option_type'] == 'PUT']['oi'].sum()

    try:
        strikes = combined_df['strike_price'].unique()
        for strike in strikes:
            ce_data = combined_df[(combined_df['strike_price'] == strike) & (combined_df['option_type'] == 'CALL')]
            pe_data = combined_df[(combined_df['strike_price'] == strike) & (combined_df['option_type'] == 'PUT')]
            
            ce_oi_val = int(ce_data['oi'].iloc[0] if not ce_data.empty else 0)
            pe_oi_val = int(pe_data['oi'].iloc[0] if not pe_data.empty else 0)
            
            ce_oi_change = ce_oi_val - prev_oi.get(f"{strike}_CE", ce_oi_val)
            pe_oi_change = pe_oi_val - prev_oi.get(f"{strike}_PE", pe_oi_val)
            
            ce_oi_change_pct = (ce_oi_change / prev_oi.get(f"{strike}_CE", 1) * 100) if prev_oi.get(f"{strike}_CE", 0) else 0
            pe_oi_change_pct = (pe_oi_change / prev_oi.get(f"{strike}_PE", 1) * 100) if prev_oi.get(f"{strike}_PE", 0) else 0
            strike_pcr = pe_oi_val / (ce_oi_val or 1)

            row = {
                "Strike": strike,
                "CE_LTP": ce_data['ltp'].iloc[0] if not ce_data.empty else 0.0,
                "CE_IV": ce_data['iv'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Delta": ce_data['delta'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Theta": ce_data['theta'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Vega": ce_data['vega'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Gamma": ce_data['gamma'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Rho": ce_data['rho'].iloc[0] if not ce_data.empty else 0.0,
                "CE_OI": ce_oi_val,
                "CE_OI_Change": ce_oi_change,
                "CE_OI_Change_Pct": ce_oi_change_pct,
                "CE_Volume": ce_data['volume'].iloc[0] if not ce_data.empty else 0,
                "CE_Bid_Ask_Spread": ce_data['bid_ask_spread'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Moneyness": ce_data['moneyness'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Intrinsic_Value": ce_data['intrinsic_value'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Time_Value": ce_data['time_value'].iloc[0] if not ce_data.empty else 0.0,
                "CE_Time_to_Expiry": ce_data['time_to_expiry'].iloc[0] if not ce_data.empty else 0,
                "PE_LTP": pe_data['ltp'].iloc[0] if not pe_data.empty else 0.0,
                "PE_IV": pe_data['iv'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Delta": pe_data['delta'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Theta": pe_data['theta'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Vega": pe_data['vega'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Gamma": pe_data['gamma'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Rho": pe_data['rho'].iloc[0] if not pe_data.empty else 0.0,
                "PE_OI": pe_oi_val,
                "PE_OI_Change": pe_oi_change,
                "PE_OI_Change_Pct": pe_oi_change_pct,
                "PE_Volume": pe_data['volume'].iloc[0] if not pe_data.empty else 0,
                "PE_Bid_Ask_Spread": pe_data['bid_ask_spread'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Moneyness": pe_data['moneyness'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Intrinsic_Value": pe_data['intrinsic_value'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Time_Value": pe_data['time_value'].iloc[0] if not pe_data.empty else 0.0,
                "PE_Time_to_Expiry": pe_data['time_to_expiry'].iloc[0] if not pe_data.empty else 0,
                "Strike_PCR": strike_pcr,
                "CE_Token": ce_data['instrument_key'].iloc[0] if not ce_data.empty else "",
                "PE_Token": pe_data['instrument_key'].iloc[0] if not pe_data.empty else ""
            }
            rows.append(row)

        df = pd.DataFrame(rows).sort_values("Strike")

        # Update previous OI
        for _, r in df.iterrows():
            prev_oi[f"{int(r['Strike'])}_CE"] = int(r['CE_OI'])
            prev_oi[f"{int(r['Strike'])}_PE"] = int(r['PE_OI'])

        if not df.empty:
            df['OI_Skew'] = (df['PE_OI'] - df['CE_OI']) / (df['PE_OI'] + df['CE_OI'] + 1)
            valid_iv = df[(df['CE_IV'] > 0) & (df['PE_IV'] > 0)]
            if len(valid_iv) >= 3:
                iv_diff = (valid_iv['PE_IV'] - valid_iv['CE_IV']).abs()
                df['IV_Skew_Slope'] = iv_diff.rolling(window=3, min_periods=1).mean().reindex(df.index, fill_value=0)
            else:
                df['IV_Skew_Slope'] = 0.0
        return df, ce_oi_total, pe_oi_total
    except Exception as e:
        logger.error(f"Option chain processing error: {e}")
        return pd.DataFrame(), 0, 0

def calculate_metrics_data(df: pd.DataFrame, ce_oi_total: int, pe_oi_total: int, spot: float):
    """Calculates key option chain metrics like PCR, Max Pain, Straddle Price, ATM Strike, ATM IV."""
    try:
        if df.empty:
            return 0, 0, 0, 0, 0

        # Find ATM strike
        atm = df.iloc[(df['Strike'] - spot).abs().argsort()[:1]]
        atm_strike = atm['Strike'].values[0] if not atm.empty else spot

        # Overall PCR
        pcr = pe_oi_total / (ce_oi_total or 1)

        # Max Pain Calculation
        min_pain = float('inf')
        max_pain = spot
        for strike in df['Strike']:
            pain = 0
            for s_call in df['Strike']:
                if s_call > strike:
                    pain += df[df['Strike'] == s_call]['CE_OI'].iloc[0] * (s_call - strike)
            for s_put in df['Strike']:
                if s_put < strike:
                    pain += df[df['Strike'] == s_put]['PE_OI'].iloc[0] * (strike - s_put)
            if pain < min_pain:
                min_pain = pain
                max_pain = strike

        # Straddle Price and ATM IV
        straddle_price = float(atm['CE_LTP'].values[0] + atm['PE_LTP'].values[0]) if not atm.empty else 0
        atm_iv = (atm['CE_IV'].values[0] + atm['PE_IV'].values[0]) / 2 if not atm.empty else 0

        return pcr, max_pain, straddle_price, atm_strike, atm_iv
    except Exception as e:
        logger.error(f"Metrics calculation error: {e}")
        return 0.0, 0.0, 0.0, 0.0, 0.0

def build_strategy_legs(combined_df: pd.DataFrame, spot_price: float, strategy_name: str, quantity: int, otm_distance: float):
    """Builds strategy legs based on combined_df."""
    try:
        quantity = int(float(quantity))
        strikes = combined_df['strike_price'].unique()
        if not strikes:
            raise ValueError("No strikes found in option chain data")

        # Find the ATM strike
        atm_strike = min(strikes, key=lambda x: abs(x - spot_price))

        legs = []

        def get_instrument_key_and_ltp(strike, opt_type):
            data = combined_df[(combined_df['strike_price'] == strike) & (combined_df['option_type'] == opt_type)]
            return data['instrument_key'].iloc[0] if not data.empty else None, data['ltp'].iloc[0] if not data.empty else 0.0

        s = strategy_name.lower()
        if s == "iron_fly":
            legs_def = [
                (atm_strike, "CE", "SELL"),
                (atm_strike, "PE", "SELL"),
                (atm_strike + otm_distance, "CE", "BUY"),
                (atm_strike - otm_distance, "PE", "BUY"),
            ]
        elif s == "iron_condor":
            legs_def = [
                (atm_strike + otm_distance, "CE", "SELL"),
                (atm_strike + 2 * otm_distance, "CE", "BUY"),
                (atm_strike - otm_distance, "PE", "SELL"),
                (atm_strike - 2 * otm_distance, "PE", "BUY"),
            ]
        elif s == "bull_put_spread":
            target_sell_strike = min(strikes, key=lambda x: abs(x - (spot_price - otm_distance)))
            target_buy_strike = min(strikes, key=lambda x: abs(x - (spot_price - 2 * otm_distance)))
            legs_def = [
                (target_sell_strike, "PE", "SELL"),
                (target_buy_strike, "PE", "BUY"),
            ]
        elif s == "bear_call_spread":
            target_sell_strike = min(strikes, key=lambda x: abs(x - (spot_price + otm_distance)))
            target_buy_strike = min(strikes, key=lambda x: abs(x - (spot_price + 2 * otm_distance)))
            legs_def = [
                (target_sell_strike, "CE", "SELL"),
                (target_buy_strike, "CE", "BUY"),
            ]
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        for strike, opt_type, action in legs_def:
            instrument_key, ltp = get_instrument_key_and_ltp(strike, opt_type)
            if instrument_key:
                legs.append({
                    "instrument_key": instrument_key,
                    "strike": strike,
                    "action": action,
                    "quantity": quantity,
                    "order_type": "MARKET",
                    "ltp": ltp
                })
            else:
                logger.warning(f"Could not find instrument key for {opt_type} at strike {strike}")

        legs = [leg for leg in legs if leg["instrument_key"]]
        if not legs:
            raise ValueError("No valid legs generated due to missing instrument keys.")
        return legs
    except Exception as e:
        logger.error(f"Strategy legs error: {e}")
        raise
