import yfinance as yf
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')

class OptionsAnalyzer:
    def __init__(self, tickers):
        self.tickers = tickers
        
    def analyze_options(self):
        logging.info(f"開始掃描 {len(self.tickers)} 檔候選股的選擇權數據...")
        results = []
        
        for symbol in self.tickers:
            try:
                # Extract clean ticker symbol if it contains formatting
                clean_symbol = symbol.split(' ')[0] if ' ' in symbol else symbol
                ticker = yf.Ticker(clean_symbol)
                
                # Get current stock price
                hist = ticker.history(period="5d")
                if hist.empty:
                    continue
                current_price = hist['Close'].iloc[-1]
                
                # Fetch available option expiration dates
                expirations = ticker.options
                if not expirations:
                    logging.info(f"  {clean_symbol}: 缺乏期權流動性數據")
                    continue
                    
                # Look for an expiration 30-45 days out (Optimal for swing trades)
                target_date = None
                for date_str in expirations:
                    days_to_exp = (pd.to_datetime(date_str) - pd.Timestamp.today()).days
                    if 20 <= days_to_exp <= 50:
                        target_date = date_str
                        break
                        
                if not target_date:
                    target_date = expirations[0] # Fallback to front month
                    
                opt = ticker.option_chain(target_date)
                calls = opt.calls
                puts = opt.puts
                
                if calls.empty or puts.empty:
                    continue
                    
                # 1. 尋找平值 (At-The-Money) 附近的 Call
                calls['abs_diff'] = abs(calls['strike'] - current_price)
                atm_call = calls.sort_values('abs_diff').iloc[0]
                
                atm_iv = atm_call['impliedVolatility']
                volume = atm_call['volume'] if pd.notna(atm_call['volume']) else 0
                bid_ask_spread = atm_call['ask'] - atm_call['bid']
                
                # 2. 計算總體 Put/Call Ratio (情緒指標)
                total_call_oi = calls['openInterest'].sum()
                total_put_oi = puts['openInterest'].sum()
                pc_ratio = total_put_oi / total_call_oi if total_call_oi > 0 else 1.0
                
                # 3. 評估這個期權是否值得交易 (過濾掉流動性極差的)
                if volume < 10 or bid_ask_spread > (atm_call['ask'] * 0.2):
                    logging.info(f"  {clean_symbol}: 期權流動性極差 (買賣價差大)，不適合交易")
                    continue
                    
                score = 0
                reasons = []
                
                # 波動率越低，買方的勝率與利潤率越高
                if atm_iv < 0.40:
                    score += 2
                    reasons.append("隱含波動率(IV)便宜，適合買入突破用的買方Call")
                elif atm_iv > 0.60:
                    score -= 1
                    reasons.append("隱含波動率(IV)偏貴，買方成本過高，勝率降低")
                    
                # P/C Ratio 若大於 1，代表市場看跌的人多，這在創新高的 VCP 股票中很容易引發軋空
                if pc_ratio > 1.2:
                    score += 2
                    reasons.append("P/C Ratio 呈現過度看空，隨時可能引發軋空反彈")
                elif pc_ratio < 0.6:
                    reasons.append("市場情緒極度看漲，追高需小心回調洗盤")
                
                # 組合結果
                strike = atm_call['strike']
                cost = atm_call['ask']
                
                recommendation = "✅ 高勝率推薦" if score >= 2 else "⚠️ 中性/觀望"
                if score < 0: recommendation = "❌ 不推薦 (成本過高)"
                
                res = f"""
【{clean_symbol} 選擇權狙擊評估 ({recommendation})】
- 目標合約: {target_date} 到期 | 履約價: ${strike} Call
- 權利金預估: 每口約 ${cost*100:.2f} 
- 數據指標: IV: {atm_iv*100:.1f}% | P/C Ratio: {pc_ratio:.2f}
- 分析: {', '.join(reasons)}
"""
                results.append((score, res))
                
                # 若為推薦等級，自動記錄以驗證勝率
                if score >= 2:
                    try:
                        import sys, os
                        sys.path.append(os.path.expanduser("~/quant_trading"))
                        from performance_tracker import log_prediction
                        # 選擇權以權利金為 entry，設定 50% 停損與 100% 停利為基礎評估
                        log_prediction(clean_symbol, f"{target_date} Call", cost, cost*0.5, cost*2.0, f"IV: {atm_iv*100:.1f}%, P/C: {pc_ratio:.1f}")
                    except Exception as e:
                        pass
                
            except Exception as e:
                logging.info(f"  {symbol} 期權解析發生錯誤: {e}")
                
        # 依照評分排序，推最強的
        results.sort(reverse=True, key=lambda x: x[0])
        print("\n" + "="*50)
        print("🎯 選擇權精選預測報告 (從 VCP 動能股中過濾)")
        print("="*50)
        for r in results:
            print(r[1])
            
if __name__ == "__main__":
    # 將刚才 screener 找出的高機率名單餵入
    vcp_list = ['NUE', 'CIEN', 'FIX', 'SLB', 'STT', 'CASY', 'NTRS']
    analyzer = OptionsAnalyzer(vcp_list)
    analyzer.analyze_options()