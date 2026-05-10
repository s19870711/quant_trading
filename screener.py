import yfinance as yf
import pandas as pd
import numpy as np
import requests
import json
import os
from bs4 import BeautifulSoup
import ta
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class Screener:
    def __init__(self, top_n=50):
        self.top_n = top_n
        self.tickers = self._get_small_mid_cap_tickers()
        # Add broad market index for RS calculation
        if 'SPY' not in self.tickers:
            self.tickers.append('SPY')

        
    def _get_small_mid_cap_tickers(self):
        try:
            logging.info("Reading local list of US stock tickers...")
            tickers = []
            
            # Load S&P 500 list
            sp500_path = os.path.expanduser("~/quant_trading/data/sp500.json")
            if os.path.exists(sp500_path):
                with open(sp500_path, 'r') as f:
                    data = json.load(f)
                    tickers.extend(data)
                    
            # Set a dynamic limit to avoid 2-hour scan runs during testing.
            # Real deployment might scan all 3000+, but let's take a sample of 200 liquid names first
            tickers = list(set(tickers))
            tickers = [str(t).replace('.', '-') for t in tickers if isinstance(t, str)]
            
            # Filter the list size
            max_scan = 1000 # Allow all standard tickers
            if len(tickers) > max_scan:
                tickers = tickers[:max_scan]
                
            logging.info(f"Successfully loaded {len(tickers)} tickers from local datastore for scanning.")
            if not tickers:
                raise ValueError("No tickers loaded from JSON")
            return tickers
        except Exception as e:
            logging.error(f"Failed to fetch local ticker files: {e}")
            # Fallback to a basket of known high-beta / growth mid-caps
            return [
                "CELH", "SMCI", "PLTR", "UPST", "MSTR", "ELF", "SYM", "CVNA", 
                "IOT", "AXON", "SNOW", "DDOG", "CRWD", "MNDY", "NET", "ZS",
                "ROKU", "HOOD", "DKNG", "COIN", "RBLX", "AFRM", "PATH", "TOST"
            ]
        
    def fetch_data(self, period="1y"):
        logging.info(f"Fetching data for {len(self.tickers)} tickers...")
        def fetch_data_in_chunks(tickers, chunk_size=50):
            data_dict = {}
            for i in range(0, len(tickers), chunk_size):
                chunk = tickers[i:i+chunk_size]
                logging.info(f"Downloading chunk {i//chunk_size + 1}/{(len(tickers)-1)//chunk_size + 1}...")
                try:
                    # Using threads=True but chunked to avoid Yahoo Finance IP rate limits
                    data = yf.download(chunk, period=period, group_by='ticker', auto_adjust=True, progress=False, threads=False)
                    for ticker in chunk:
                        if len(chunk) == 1:
                            df = data.copy()
                            if isinstance(df, pd.DataFrame) and 'Close' in df.columns:
                                df.dropna(inplace=True)
                                if len(df) > 50 and df['Close'].iloc[-1] > 0 and not pd.isna(df['Close'].iloc[-1]):
                                    data_dict[ticker] = df
                            continue
                        elif isinstance(data.columns, pd.MultiIndex):
                            if ticker in data.columns.levels[0]:
                                df = data[ticker].copy()
                            else:
                                continue
                        else:
                            continue
                            
                        df.dropna(inplace=True)
                        if len(df) > 50:
                            if df['Close'].iloc[-1] > 0 and not pd.isna(df['Close'].iloc[-1]):
                                data_dict[ticker] = df
                except Exception as e:
                    logging.warning(f"Error fetching chunk: {e}")
                
                # Sleep to respect rate limits
                import time
                time.sleep(2)
            
            return data_dict

        self.data_dict = fetch_data_in_chunks(self.tickers)

    def calculate_vcp_rules(self, ticker, df):
        """
        Calculates Mark Minervini's VCP criteria with ADX and RS Rating filters.
        """
        try:
            if ticker == 'SPY' or len(df) < 200:
                return False
                
            close = df['Close']
            
            # --- Base Trend Filters ---
            df['SMA_50'] = close.rolling(window=50).mean()
            df['SMA_150'] = close.rolling(window=150).mean()
            df['SMA_200'] = close.rolling(window=200).mean()
            
            # Fix calculating 52-week high/low with pandas rolling issue (NaNs at the end)
            high_52w = df['Close'].tail(252).max()
            low_52w = df['Close'].tail(252).min()
            
            current_close = close.iloc[-1]
            sma50 = df['SMA_50'].iloc[-1]
            sma150 = df['SMA_150'].iloc[-1]
            sma200 = df['SMA_200'].iloc[-1]
            
            # 200 SMA trending up 1-month
            sma200_20days_ago = df['SMA_200'].iloc[-20] if len(df) > 200 else float('inf')

            # Calculate conditions, VCP Style rules restored and integrated with ADX/RS Rating
            condition_1 = current_close > sma150 and current_close > sma200
            condition_2 = sma150 > sma200
            condition_3 = sma50 > sma150 and sma50 > sma200
            
            # Condition 4: Current Price > 50-day SMA
            condition_4 = current_close > sma50
            
            # Must be near new highs for genuine VCP
            condition_5 = current_close >= (high_52w * 0.85) # Within 15% of 52-week high
            condition_6 = current_close >= (low_52w * 1.30)  # Up 30% from 52-week low
            
            # --- High Star Strategy 1: ADX Momentum Filter ---
            try:
                adx_indicator = ta.trend.ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
                df['ADX'] = adx_indicator.adx()
                current_adx = df['ADX'].iloc[-1]
                condition_adx = pd.notna(current_adx) and current_adx >= 25 # Increased strictness back to strong trend
            except Exception:
                condition_adx = False
                
            # --- High Star Strategy 2: Relative Strength (Simplified vs SPY) ---
            try:
                spy_df = self.data_dict.get('SPY')
                if spy_df is None or len(spy_df) < 126:
                    condition_rs = True
                else:
                    stock_return = (current_close / close.iloc[-126]) - 1
                    spy_return = (spy_df['Close'].iloc[-1] / spy_df['Close'].iloc[-126]) - 1
                    condition_rs = stock_return > spy_return # Must outperform SPY naturally without relaxing
            except Exception:
                condition_rs = True 

            # Condition 7: Volume Contraction check VCP style
            vol_50d_avg = df['Volume'].tail(50).mean()
            vol_last_5d_max = df['Volume'].tail(5).max()
            vol_last_3d_min = df['Volume'].tail(3).min()
            
            # VCP requires both: recent dry up AND not massive selling volume lately
            condition_7_dry = vol_last_3d_min < (vol_50d_avg * 0.65) # Strict dry up
            condition_7_cap = vol_last_5d_max < (vol_50d_avg * 1.25) # No recent massive selling
            condition_7 = condition_7_dry and condition_7_cap

            if (condition_1 and condition_2 and condition_3 and condition_4 and 
                condition_5 and condition_6 and condition_7 and condition_adx and condition_rs):
                return True
        except Exception as e:
            return False
            
        return False
        
    def find_vcp_candidates(self):
        logging.info("Scanning for VCP + ADX/RS candidates...")
        candidates = []
        for ticker, df in self.data_dict.items():
            if self.calculate_vcp_rules(ticker, df):
                # Calculate Trade Plan based on VCP breakout
                close = df['Close'].iloc[-1]
                adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 0
                
                recent_high = df['High'].tail(5).max()
                recent_low = df['Low'].tail(5).min()
                
                entry_price = recent_high * 1.002 # Breakout trigger (slightly above 5-day base)
                stop_loss = recent_low * 0.99 # Stop just below 5-day base
                if (entry_price - stop_loss) / entry_price > 0.08:
                    stop_loss = entry_price * 0.92 # Max 8% risk stop
                    
                target_price = entry_price + ((entry_price - stop_loss) * 2.5) # 1:2.5 Risk/Reward ratio
                
                plan = f"{ticker} | 突破買入: ${entry_price:.2f} | 停損: ${stop_loss:.2f} | 停利: ${target_price:.2f} | ADX: {adx:.1f}"
                candidates.append(plan)
        
        logging.info(f"Found {len(candidates)} high-probability candidates: {candidates}")
        return candidates

if __name__ == "__main__":
    screener = Screener()
    screener.fetch_data()
    vcp_stocks = screener.find_vcp_candidates()
    
    # In full system, this would write to trading_memory.db or trigger Telegram
    print("\n--- SCREENER RESULTS ---")
    print(f"VCP Setup Detected in: {vcp_stocks}")
