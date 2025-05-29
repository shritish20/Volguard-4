import pandas as pd
import numpy as np
from datetime import datetime
from app.config import logger

# Global variable for previous OI (simplified state management for a single-user demo)
prev_oi = {}

def process_chain_data(data: list):
    """Processes raw option chain data into a structured DataFrame."""
    global prev_oi
    rows = []
    ce_oi_total = 0
    pe_oi_total = 0

    try:
        for r in data:
            ce = r.get('call_options', {})
            pe = r.get('put_options', {})
            ce_md, pe_md = ce.get('market_data', {}), pe.get('market_data', {})
            ce_gk, pe_gk = ce.get('option_greeks', {}), pe.get('option_greeks', {})
            strike = r.get('strike_price', 0)

            ce_oi_val = int(ce_md.get("oi", 0) or 0)
            pe_oi_val = int(pe_md.get("oi", 0) or 0)

            ce_oi_change = ce_oi_val - prev_oi.get(f"{strike}_CE", ce_oi_val)
            pe_oi_change = pe_oi_val - prev_oi.get(f"{strike}_PE", pe_oi_val)

            # Avoid division by zero for percentage change
            ce_oi_change_pct = (ce_oi_change / prev_oi.get(f"{strike}_CE", 1) * 100) if prev_oi.get(f"{strike}_CE", 0) else 0
            pe_oi_change_pct = (pe_oi_change / prev_oi.get(f"{strike}_PE", 1) * 100) if prev_oi.get(f"{strike}_PE", 0) else 0

            strike_pcr = pe_oi_val / (ce_oi_val or 1)

            row = {
                "Strike": strike,
                "CE_LTP": ce_md.get("ltp", 0.0) or 0.0,
                "CE_IV": ce_gk.get("iv", 0.0) or 0.0,
                "CE_Delta": ce_gk.get("delta", 0.0) or 0.0,
                "CE_Theta": ce_gk.get("theta", 0.0) or 0.0,
                "CE_Vega": ce_gk.get("vega", 0.0) or 0.0,
                "CE_OI": ce_oi_val,
                "CE_OI_Change": ce_oi_change,
                "CE_OI_Change_Pct": ce_oi_change_pct,
                "CE_Volume": ce_md.get("volume", 0) or 0,

                "PE_LTP": pe_md.get("ltp", 0.0) or 0.0,
                "PE_IV": pe_gk.get("iv", 0.0) or 0.0,
                "PE_Delta": pe_gk.get("delta", 0.0) or 0.0,
                "PE_Theta": pe_gk.get("theta", 0.0) or 0.0,
                "PE_Vega": pe_gk.get("vega", 0.0) or 0.0,
                "PE_OI": pe_oi_val,
                "PE_OI_Change": pe_oi_change,
                "PE_OI_Change_Pct": pe_oi_change_pct,
                "PE_Volume": pe_md.get("volume", 0) or 0,
                "Strike_PCR": strike_pcr,
                "CE_Token": ce.get("instrument_key", ""),
                "PE_Token": pe.get("instrument_key", "")
            }
            ce_oi_total += ce_oi_val
            pe_oi_total += pe_oi_val
            rows.append(row)

        df = pd.DataFrame(rows).sort_values("Strike")

        # Update previous OI for next run
        for _, r in df.iterrows():
            prev_oi[f"{int(r['Strike'])}_CE"] = int(r['CE_OI'])
            prev_oi[f"{int(r['Strike'])}_PE"] = int(r['PE_OI'])

        if not df.empty:
            df['OI_Skew'] = (df['PE_OI'] - df['CE_OI']) / (df['PE_OI'] + df['CE_OI'] + 1)
            valid_iv = df[(df['CE_IV'] > 0) & (df['PE_IV'] > 0)]
            if len(valid_iv) >= 3:
                # Calculate IV skew based on difference and a rolling mean for smoothing
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

def build_strategy_legs(option_chain_data: list, spot_price: float, strategy_name: str, quantity: int, otm_distance: float):
    """Builds strategy legs based on option chain data."""
    try:
        quantity = int(float(quantity))
        strikes = [leg['strike_price'] for leg in option_chain_data if 'strike_price' in leg]
        if not strikes:
            raise ValueError("No strikes found in option chain data")

        # Find the ATM strike based on spot price
        atm_strike = min(strikes, key=lambda x: abs(x - spot_price))

        legs = []

        def get_instrument_key_and_ltp(strike, opt_type):
            for leg_data in option_chain_data:
                if leg_data.get('strike_price') == strike:
                    if opt_type == 'CE' and 'call_options' in leg_data:
                        return leg_data['call_options'].get('instrument_key'), leg_data['call_options'].get('market_data', {}).get('ltp', 0.0)
                    elif opt_type == 'PE' and 'put_options' in leg_data:
                        return leg_data['put_options'].get('instrument_key'), leg_data['put_options'].get('market_data', {}).get('ltp', 0.0)
            return None, 0.0

        s = strategy_name.lower()
        if s == "iron_fly":
            # Sell ATM CE, Sell ATM PE, Buy OTM CE, Buy OTM PE
            legs_def = [
                (atm_strike, "CE", "SELL"),
                (atm_strike, "PE", "SELL"),
                (atm_strike + otm_distance, "CE", "BUY"),
                (atm_strike - otm_distance, "PE", "BUY"),
            ]
        elif s == "iron_condor":
            # Sell OTM Call, Buy Far OTM Call, Sell OTM Put, Buy Far OTM Put
            legs_def = [
                (atm_strike + otm_distance, "CE", "SELL"),
                (atm_strike + 2 * otm_distance, "CE", "BUY"),
                (atm_strike - otm_distance, "PE", "SELL"),
                (atm_strike - 2 * otm_distance, "PE", "BUY"),
            ]
        elif s == "bull_put_spread":
            # Sell OTM Put, Buy Far OTM Put
            legs_def = [
                (atm_strike - otm_distance, "PE", "SELL"), # Sell ITM/ATM put
                (atm_strike - (otm_distance * 2 if otm_distance > 0 else 50), "PE", "BUY"), # Buy further OTM put
            ]
            # Adjust strikes for bull put spread logic: Sell higher strike put, Buy lower strike put
            # Let's redefine for clarity: Sell OTM (e.g., atm_strike - 50), Buy further OTM (atm_strike - 100)
            target_sell_strike = min(strikes, key=lambda x: abs(x - (spot_price - otm_distance)))
            target_buy_strike = min(strikes, key=lambda x: abs(x - (spot_price - 2 * otm_distance)))
            legs_def = [
                (target_sell_strike, "PE", "SELL"),
                (target_buy_strike, "PE", "BUY"),
            ]
        elif s == "bear_call_spread":
            # Sell OTM Call, Buy Far OTM Call
            # Let's redefine for clarity: Sell OTM (e.g., atm_strike + 50), Buy further OTM (atm_strike + 100)
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
                    "ltp": ltp # Include LTP for later P&L estimation
                })
            else:
                logger.warning(f"Could not find instrument key for {opt_type} at strike {strike}")


        legs = [leg for leg in legs if leg["instrument_key"]] # Filter out legs where instrument_key couldn't be found
        if not legs:
            raise ValueError("No valid legs generated due to missing instrument keys. Check OTM distance or option chain data.")
        return legs
    except Exception as e:
        logger.error(f"Strategy legs error: {e}")
        raise
