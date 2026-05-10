import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

class Screener:
    def __init__(self, top_n=50):
        self.top_n = top_n
        self.tickers = self._get_nasdaq100_tickers()
        
    def _get_nasdaq100_tickers(self):
        try:
            logging.info("Fetching NASDAQ 100 tickers from Wikipedia...")
            df = pd.read_html("https://en.wikipedia.org/wiki/Nasdaq-100")[4]
            tickers = df['Ticker'].tolist()
            # Clean up tickers for Yahoo Finance (e.g., BRK.B -> BRK-B)
            tickers = [t.replace('.', '-') for t in tickers]
            return tickers
        except Exception as e:
            logging.error(f"Failed to fetch NASDAQ 100 tickers: {e}")
            # Fallback to top 30 liquid tech stocks
            return [
                "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AVGO",
                "COST", "PEP", "ADBE", "CSCO", "NFLX", "AMD", "CMCSA", "INTC", 
                "INTU", "QCOM", "TXN", "AMAT", "HON", "AMGN", "SBUX", "ISRG",
                "GILD", "VRTX", "MDLZ", "BKNG", "ADI", "ADP"
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

    def calculate_vcp_rules(self, df):
        """
        Calculates Mark Minervini's specific VCP (Volatility Contraction Pattern) criteria:
        1. Price > 150 SMA and 200 SMA
        2. 150 SMA > 200 SMA
        3. 200 SMA is trending up (at least 1 month)
        4. 50 SMA > 150 SMA and 200 SMA
        5. Price > 50 SMA
        6. Current Price is at least 30% above 52-week low
        7. Current price is within 25% of 52-week high
        """
        try:
            close = df['Close']
            
            df['SMA_50'] = close.rolling(window=50).mean()
            df['SMA_150'] = close.rolling(window=150).mean()
            df['SMA_200'] = close.rolling(window=200).mean()
            
            high_52w = close.rolling(window=252).max().iloc[-1]
            low_52w = close.rolling(window=252).min().iloc[-1]
            
            current_close = close.iloc[-1]
            sma50 = df['SMA_50'].iloc[-1]
            sma150 = df['SMA_150'].iloc[-1]
            sma200 = df['SMA_200'].iloc[-1]
            
            # 200 SMA trending up 1-month
            sma200_20days_ago = df['SMA_200'].iloc[-20] if len(df) > 200 else float('inf')

            condition_1 = current_close > sma150 and current_close > sma200
            condition_2 = sma150 > sma200
            condition_3 = sma200 > sma200_20days_ago
            condition_4 = sma50 > sma150 and sma50 > sma200
            condition_5 = current_close > sma50
            condition_6 = current_close >= (low_52w * 1.30)
            condition_7 = current_close >= (high_52w * 0.75)
            
            # Simple volume contraction check: last 5 days volume < 50 day average
            vol_50d_avg = df['Volume'].rolling(window=50).mean().iloc[-1]
            vol_last_5d_max = df['Volume'].tail(5).max()
            condition_8 = vol_last_5d_max < vol_50d_avg * 1.5 # Relaxed contraction for volatile markets

            if (condition_1 and condition_2 and condition_3 and condition_4 and 
                condition_5 and condition_6 and condition_7 and condition_8):
                return True
        except Exception as e:
            return False
            
        return False
        
    def find_vcp_candidates(self):
        logging.info("Scanning for VCP candidates...")
        candidates = []
        for ticker, df in self.data_dict.items():
            if self.calculate_vcp_rules(df):
                candidates.append(ticker)
        
        logging.info(f"Found {len(candidates)} VCP candidates: {candidates}")
        return candidates

if __name__ == "__main__":
    screener = Screener()
    screener.fetch_data()
    vcp_stocks = screener.find_vcp_candidates()
    
    # In full system, this would write to trading_memory.db or trigger Telegram
    print("\n--- SCREENER RESULTS ---")
    print(f"VCP Setup Detected in: {vcp_stocks}")
