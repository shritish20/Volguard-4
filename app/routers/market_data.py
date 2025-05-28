from fastapi import APIRouter, HTTPException
from datetime import datetime
import pandas as pd
import requests
from app.config import settings, logger
from app.models import OptionChainInput
from app.utils.upstox_helpers import fetch_expiry, fetch_option_chain_raw, get_upstox_config
from app.utils.data_processing import process_chain_data, calculate_metrics_data
from app.utils.volatility_calcs import compute_realized_vol

router = APIRouter()

class ComprehensiveOptionChainFetcher:
    def __init__(self, access_token):
        self.access_token = access_token
        self.base_url = settings.UPSTOX_BASE_URL  # Assumed as https://api.upstox.com
        self.headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def get_option_chain(self, instrument_key, expiry_date):
        url = f"{self.base_url}/v2/option/chain"
        params = {'instrument_key': instrument_key, 'expiry_date': expiry_date}
        try:
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching option chain: {e}")
            raise HTTPException(status_code=e.response.status_code if e.response else 500, detail=str(e))

    def parse_comprehensive_option_data(self, option_chain_data):
        if not option_chain_data or 'data' not in option_chain_data:
            return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {}, 0

        calls_list = []
        puts_list = []

        for strike_data in option_chain_data['data']:
            strike_price = strike_data.get('strike_price', 0)
            underlying_spot_price = strike_data.get('underlying_spot_price', 0)
            expiry = strike_data.get('expiry', '')

            if 'call_options' in strike_data:
                call_data = strike_data['call_options']
                call_market = call_data.get('market_data', {})
                call_analytics = call_data.get('option_greeks', {})
                call_row = {
                    'option_type': 'CALL',
                    'strike_price': strike_price,
                    'underlying_spot_price': underlying_spot_price,
                    'expiry': expiry,
                    'pcr': strike_data.get('pcr', 0),
                    'ltp': call_market.get('ltp', 0),
                    'volume': call_market.get('volume', 0),
                    'oi': call_market.get('oi', 0),
                    'close_price': call_market.get('close_price', 0),
                    'bid_price': call_market.get('bid_price', 0),
                    'ask_price': call_market.get('ask_price', 0),
                    'bid_qty': call_market.get('bid_qty', 0),
                    'ask_qty': call_market.get('ask_qty', 0),
                    'vega': call_analytics.get('vega', 0),
                    'theta': call_analytics.get('theta', 0),
                    'gamma': call_analytics.get('gamma', 0),
                    'delta': call_analytics.get('delta', 0),
                    'iv': call_analytics.get('iv', 0),
                    'rho': call_analytics.get('rho', 0),
                    'instrument_key': call_data.get('instrument_key', ''),
                }
                calls_list.append(call_row)

            if 'put_options' in strike_data:
                put_data = strike_data['put_options']
                put_market = put_data.get('market_data', {})
                put_analytics = put_data.get('option_greeks', {})
                put_row = {
                    'option_type': 'PUT',
                    'strike_price': strike_price,
                    'underlying_spot_price': underlying_spot_price,
                    'expiry': expiry,
                    'pcr': strike_data.get('pcr', 0),
                    'ltp': put_market.get('ltp', 0),
                    'volume': put_market.get('volume', 0),
                    'oi': put_market.get('oi', 0),
                    'close_price': put_market.get('close_price', 0),
                    'bid_price': put_market.get('bid_price', 0),
                    'ask_price': put_market.get('ask_price', 0),
                    'bid_qty': put_market.get('bid_qty', 0),
                    'ask_qty': put_market.get('ask_qty', 0),
                    'vega': put_analytics.get('vega', 0),
                    'theta': put_analytics.get('theta', 0),
                    'gamma': put_analytics.get('gamma', 0),
                    'delta': put_analytics.get('delta', 0),
                    'iv': put_analytics.get('iv', 0),
                    'rho': put_analytics.get('rho', 0),
                    'instrument_key': put_data.get('instrument_key', ''),
                }
                puts_list.append(put_row)

        calls_df = pd.DataFrame(calls_list)
        puts_df = pd.DataFrame(puts_list)
        combined_df = pd.concat([calls_df, puts_df], ignore_index=True)

        if not combined_df.empty:
            combined_df['moneyness'] = combined_df['strike_price'] / combined_df['underlying_spot_price']
            combined_df['intrinsic_value'] = combined_df.apply(
                lambda row: max(0, row['underlying_spot_price'] - row['strike_price']) if row['option_type'] == 'CALL'
                else max(0, row['strike_price'] - row['underlying_spot_price']), axis=1
            )
            combined_df['time_value'] = combined_df['ltp'] - combined_df['intrinsic_value']
            combined_df['oi_change'] = 0  # Placeholder, updated in process_chain_data
            combined_df['volume_oi_ratio'] = combined_df['volume'] / (combined_df['oi'] + 1)
            combined_df['bid_ask_spread'] = combined_df['ask_price'] - combined_df['bid_price']
            combined_df['time_to_expiry'] = combined_df['expiry'].apply(
                lambda x: (datetime.strptime(x, '%Y-%m-%d').date() - datetime.now().date()).days if x else 0
            )

        atm_data = {}
        if not combined_df.empty:
            spot_price = combined_df['underlying_spot_price'].iloc[0]
            combined_df['strike_diff'] = abs(combined_df['strike_price'] - spot_price)
            atm_strike = combined_df.loc[combined_df['strike_diff'].idxmin(), 'strike_price']
            atm_call = combined_df[(combined_df['strike_price'] == atm_strike) & (combined_df['option_type'] == 'CALL')]
            atm_put = combined_df[(combined_df['strike_price'] == atm_strike) & (combined_df['option_type'] == 'PUT')]
            atm_data = {
                'atm_strike': atm_strike,
                'spot_price': spot_price,
                'atm_call_iv': atm_call['iv'].iloc[0] if not atm_call.empty else 0,
                'atm_put_iv': atm_put['iv'].iloc[0] if not atm_put.empty else 0,
                'atm_call_premium': atm_call['ltp'].iloc[0] if not atm_call.empty else 0,
                'atm_put_premium': atm_put['ltp'].iloc[0] if not atm_put.empty else 0,
                'atm_call_delta': atm_call['delta'].iloc[0] if not atm_call.empty else 0,
                'atm_put_delta': atm_put['delta'].iloc[0] if not atm_put.empty else 0,
                'atm_call_oi': atm_call['oi'].iloc[0] if not atm_call.empty else 0,
                'atm_put_oi': atm_put['oi'].iloc[0] if not atm_put.empty else 0,
                'atm_straddle_price': (atm_call['ltp'].iloc[0] if not atm_call.empty else 0) +
                                     (atm_put['ltp'].iloc[0] if not atm_put.empty else 0)
            }

        max_pain = 0
        if not (calls_df.empty or puts_df.empty):
            strikes = sorted(set(calls_df['strike_price']).union(set(puts_df['strike_price'])))
            total_losses = []
            for expiry_price in strikes:
                call_loss = sum(
                    (expiry_price - row['strike_price']) * row['oi']
                    for _, row in calls_df.iterrows() if expiry_price > row['strike_price']
                )
                put_loss = sum(
                    (row['strike_price'] - expiry_price) * row['oi']
                    for _, row in puts_df.iterrows() if expiry_price < row['strike_price']
                )
                total_losses.append((expiry_price, call_loss + put_loss))
            max_pain = min(total_losses, key=lambda x: x[1])[0] if total_losses else 0

        return calls_df, puts_df, combined_df, atm_data, max_pain

@router.post("/option-chain", summary="Fetches and processes live option chain data")
async def get_option_chain_endpoint(data: OptionChainInput):
    try:
        config = get_upstox_config(data.access_token)
        fetcher = ComprehensiveOptionChainFetcher(data.access_token)
        
        expiry = await fetch_expiry(config, data.instrument_key)
        if not expiry:
            logger.error("Failed to retrieve nearest expiry date.")
            raise HTTPException(status_code=500, detail="Failed to retrieve nearest expiry date.")

        chain = await fetch_option_chain_raw(config, data.instrument_key, expiry)
        if not chain:
            logger.error("Failed to retrieve option chain data.")
            raise HTTPException(status_code=500, detail="Failed to retrieve option chain data.")

        spot = chain[0].get("underlying_spot_price") if chain else None
        if not spot:
            logger.error("Failed to retrieve spot price from option chain.")
            raise HTTPException(status_code=500, detail="Failed to retrieve spot price.")

        _, _, combined_df, atm_data, max_pain = fetcher.parse_comprehensive_option_data(chain)
        if combined_df.empty:
            logger.error("Processed option chain DataFrame is empty.")
            raise HTTPException(status_code=500, detail="Processed option chain DataFrame is empty.")

        df_processed, ce_oi, pe_oi = process_chain_data(combined_df)
        if df_processed.empty:
            logger.error("Processed option chain DataFrame is empty.")
            raise HTTPException(status_code=500, detail="Processed option chain DataFrame is empty.")

        pcr, _, straddle_price, atm_strike, atm_iv = calculate_metrics_data(df_processed, ce_oi, pe_oi, spot)

        response_data = {
            "nifty_spot": spot,
            "atm_strike": atm_strike,
            "straddle_price": straddle_price,
            "pcr": round(pcr, 2),
            "max_pain": max_pain,
            "expiry": expiry,
            "iv_skew_data": df_processed.to_dict(orient='records'),
            "atm_iv": round(atm_iv, 2),
            "realized_volatility": compute_realized_vol(),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data": chain
        }
        logger.info("Successfully fetched and processed market data via /option-chain.")
        return response_data
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.exception("An unexpected error occurred in /option-chain endpoint.")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
