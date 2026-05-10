import sqlite3
import yfinance as yf
import pandas as pd
from datetime import datetime
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

DB_PATH = os.path.expanduser("~/trading_memory.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        symbol TEXT,
        asset_type TEXT,
        entry_price REAL,
        stop_loss REAL,
        target_price REAL,
        status TEXT,
        notes TEXT
    )''')
    conn.commit()
    conn.close()

def log_prediction(symbol, asset_type, entry, stop, target, notes=""):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    
    # 避免同一天重複寫入相同的預測
    c.execute("SELECT id FROM predictions WHERE date=? AND symbol=? AND asset_type=?", (today, symbol, asset_type))
    if not c.fetchone():
        c.execute('''INSERT INTO predictions 
                     (date, symbol, asset_type, entry_price, stop_loss, target_price, status, notes) 
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                  (today, symbol, asset_type, entry, stop, target, "pending", notes))
        logging.info(f"已記錄預測 -> {symbol} {asset_type} (Entry: {entry})")
    conn.commit()
    conn.close()

def evaluate_predictions():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM predictions WHERE status IN ('pending', 'active')", conn)
    
    if df.empty:
        logging.info("目前沒有待驗證的預測記錄。")
        return "無待驗證預測"

    updated_count = 0
    for _, row in df.iterrows():
        symbol = row['symbol']
        status = row['status']
        entry = row['entry_price']
        target = row['target_price']
        stop = row['stop_loss']
        
        try:
            hist = yf.Ticker(symbol).history(period="5d")
            if hist.empty: continue
            
            # 使用近 3 天的高低點來確認是否觸發
            recent_high = hist['High'].max()
            recent_low = hist['Low'].min()
            
            new_status = status
            
            # 狀態轉換邏輯
            if status == "pending":
                if recent_high >= entry:
                    new_status = "active" # 突破進場價，開始計算損益
            
            if new_status == "active":
                if recent_high >= target:
                    new_status = "win" # 達到獲利目標
                elif recent_low <= stop:
                    new_status = "loss" # 打到停損點
                    
            if new_status != status:
                c = conn.cursor()
                c.execute("UPDATE predictions SET status=? WHERE id=?", (new_status, row['id']))
                conn.commit()
                logging.info(f"⭐ 更新預測狀態: {symbol} 從 {status} 變成 -> {new_status}")
                updated_count += 1

        except Exception as e:
            logging.error(f"驗證 {symbol} 時發生錯誤: {e}")
            
    # 統計勝率
    c = conn.cursor()
    c.execute("SELECT count(*) FROM predictions WHERE status='win'")
    wins = c.fetchone()[0]
    c.execute("SELECT count(*) FROM predictions WHERE status='loss'")
    losses = c.fetchone()[0]
    total_closed = wins + losses
    win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
    
    conn.close()
    
    report = f"📝 驗證完成: 本次更新 {updated_count} 筆。歷史結算共 {total_closed} 筆，目前策略勝率: {win_rate:.1f}%"
    logging.info(report)
    return report

if __name__ == "__main__":
    report = evaluate_predictions()
    print(report)