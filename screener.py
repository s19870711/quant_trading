import yfinance as yf
import pandas as pd
import numpy as np
import requests
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
            logging.info("Fetching S&P 400 MidCap and S&P 600 SmallCap tickers from Wikipedia...")
            # S&P 400 MidCap
            df_400 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies")[0]
            tickers_400 = df_400['Symbol'].tolist()
            
            # S&P 600 SmallCap
            df_600 = pd.read_html("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies")[0]
            tickers_600 = df_600['Symbol'].tolist()
            
            tickers = tickers_400 + tickers_600
            
            # Clean up tickers for Yahoo Finance (e.g., BRK.B -> BRK-B)
            tickers = [str(t).replace('.', '-') for t in tickers if isinstance(t, str)]
            
            logging.info(f"Successfully loaded {len(tickers)} Small/Mid-Cap tickers.")
            return tickers
        except Exception as e:
            logging.error(f"Failed to fetch Small/Mid-Cap tickers: {e}")
            # Fallback to a basket of known high-beta / growth mid-caps
            return [
                "CELH", "SMCI", "PLTR", "UPST", "MSTR", "ELF", "SYM", "CVNA", 
                "IOT", "AXON", "SNOW", "DDOG", "CRWD", "MNDY", "NET", "ZS",
                "ROKU", "HOOD", "DKNG", "COIN", "RBLX", "AFRM", "PATH", "TOST"
            ]
        
    def fetch_data(self, period="1y"):
        logging.info(f"Fetching data for {len(self.tickers)} tickers...")
        # Download all tickers at once for efficiency
        data = yf.download(self.tickers, period=period, group_by='ticker', auto_adjust=True, progress=False)
        self.data_dict = {}
        
        for ticker in self.tickers:
            if isinstance(data.columns, pd.MultiIndex):
                 df = data[ticker].copy()
            else:
                 df = data.copy()
            
            df.dropna(inplace=True)
            if len(df) > 50: # Require at least 50 days of data
                self.data_dict[ticker] = df

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
            
            high_52w = close.rolling(window=252).max().iloc[-1]
            low_52w = close.rolling(window=252).min().iloc[-1]
            
            current_close = close.iloc[-1]
            sma50 = df['SMA_50'].iloc[-1]
            sma150 = df['SMA_150'].iloc[-1]
            sma200 = df['SMA_200'].iloc[-1]
            
            sma200_20days_ago = df['SMA_200'].iloc[-20] if len(df) > 200 else float('inf')

            condition_1 = current_close > sma150 and current_close > sma200
            condition_2 = sma150 > sma200
            condition_3 = sma200 > sma200_20days_ago
            condition_4 = sma50 > sma150 and sma50 > sma200
            condition_5 = current_close > sma50
            condition_6 = current_close >= (low_52w * 1.30)
            condition_7 = current_close >= (high_52w * 0.75)
            
            # --- High Star Strategy 1: ADX Momentum Filter ---
            # Using 'ta' library to calculate ADX. Generally ADX > 20 means strong trend.
            adx_indicator = ta.trend.ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
            df['ADX'] = adx_indicator.adx()
            current_adx = df['ADX'].iloc[-1]
            condition_adx = current_adx >= 20
            
            # --- High Star Strategy 2: Relative Strength (Simplified vs SPY) ---
            # Does the stock significantly outperform SPY over a 6-month (126 days) window?
            try:
                spy_df = self.data_dict['SPY']
                stock_return = (current_close / close.iloc[-126]) - 1
                spy_return = (spy_df['Close'].iloc[-1] / spy_df['Close'].iloc[-126]) - 1
                condition_rs = stock_return > (spy_return * 1.5) # Outperform SPY by 50%
            except Exception:
                condition_rs = True # Bypass if SPY data missing
            
            # --- Volume Contraction Check ---
            vol_50d_avg = df['Volume'].rolling(window=50).mean().iloc[-1]
            vol_last_5d_max = df['Volume'].tail(5).max()
            # Relaxed for initial pool building
            condition_8 = vol_last_5d_max < vol_50d_avg * 1.8 

            if (condition_1 and condition_2 and condition_3 and condition_4 and 
                condition_5 and condition_6 and condition_7 and condition_8 and 
                condition_adx and condition_rs):
                return True
        except Exception as e:
            return False
            
        return False
        
    def find_vcp_candidates(self):
        logging.info("Scanning for VCP + ADX/RS candidates...")
        candidates = []
        for ticker, df in self.data_dict.items():
            if self.calculate_vcp_rules(ticker, df):
                candidates.append(ticker)
        
        logging.info(f"Found {len(candidates)} high-probability candidates: {candidates}")
        return candidates

if __name__ == "__main__":
    screener = Screener()
    screener.fetch_data()
    vcp_stocks = screener.find_vcp_candidates()
    
    # In full system, this would write to trading_memory.db or trigger Telegram
    print("\n--- SCREENER RESULTS ---")
    print(f"VCP Setup Detected in: {vcp_stocks}")
