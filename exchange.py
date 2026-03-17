import pandas as pd
import sqlite3
import time
import os
import signal
import sys
from collections import deque
import threading
import csv

DB_NAME = 'hft_results.db'
CSV_NAME = 'market_data.csv'

class HFTBacktester:
    def __init__(self):
        self.conn = None
        self.running = True
        self.position = 0  # Track current position
        self.cash = 100000  # Starting cash
        self.trades = []
        self.price_buffer = deque(maxlen=50)  # Store last 50 prices for analysis
        self.signal_threshold = 0.0005  # 0.05% threshold
        self.last_position = 0  # Track last file position for incremental reading
        
        # Setup signal handling
        signal.signal(signal.SIGINT, self.signal_handler)
        
    def signal_handler(self, sig, frame):
        print("\nShutting down backtester...")
        self.running = False
        
    def init_db(self):
        """Initialize database with proper indexes"""
        self.conn = sqlite3.connect(DB_NAME, timeout=10)
        cursor = self.conn.cursor()
        
        # Drop and recreate tables
        cursor.execute("DROP TABLE IF EXISTS portfolio")
        cursor.execute("DROP TABLE IF EXISTS daily_summary")
        
        # Portfolio table with proper schema
        cursor.execute("""
            CREATE TABLE portfolio (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                action TEXT,
                price REAL,
                quantity INTEGER,
                position_after INTEGER,
                cash_after REAL,
                reason TEXT
            )
        """)
        
        # Daily summary table
        cursor.execute("""
            CREATE TABLE daily_summary (
                date TEXT PRIMARY KEY,
                total_trades INTEGER,
                total_volume INTEGER,
                net_pnl REAL,
                sharpe_ratio REAL,
                max_drawdown REAL,
                win_rate REAL
            )
        """)
        
        # Create indexes for performance
        cursor.execute("CREATE INDEX idx_timestamp ON portfolio(timestamp)")
        cursor.execute("CREATE INDEX idx_action ON portfolio(action)")
        
        self.conn.commit()
        print("Database initialized successfully")
        
    def calculate_metrics(self, prices):
        """Calculate trading metrics"""
        if len(prices) < 2:
            return 0, 0
            
        returns = pd.Series(prices).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * (252 ** 0.5) if returns.std() > 0 else 0
        max_dd = (returns.cumsum().cummax() - returns.cumsum()).max()
        
        return sharpe, max_dd
        
    def execute_trade(self, action, price, reason):
        """Execute trade with position tracking"""
        quantity = 100  # Fixed quantity for simplicity
        
        if action == 'BUY' and self.position == 0:
            cost = price * quantity
            if self.cash >= cost:
                self.cash -= cost
                self.position = quantity
                trade_record = (time.strftime('%H:%M:%S'), action, price, 
                              quantity, self.position, self.cash, reason)
                
                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO portfolio 
                    (timestamp, action, price, quantity, position_after, cash_after, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, trade_record)
                self.conn.commit()
                
                self.trades.append({
                    'timestamp': trade_record[0],
                    'action': action,
                    'price': price,
                    'quantity': quantity
                })
                
                print(f"[{trade_record[0]}] {action} {quantity} @ ${price:.2f} | "
                      f"Position: {self.position} | Cash: ${self.cash:.2f} | {reason}")
                
        elif action == 'SELL' and self.position > 0:
            revenue = price * self.position
            self.cash += revenue
            trade_record = (time.strftime('%H:%M:%S'), action, price, 
                          self.position, 0, self.cash, reason)
            
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio 
                (timestamp, action, price, quantity, position_after, cash_after, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, trade_record)
            self.conn.commit()
            
            # Calculate P&L for this trade
            buy_price = self.trades[-1]['price'] if self.trades else price
            pnl = (price - buy_price) * self.position
            
            self.trades.append({
                'timestamp': trade_record[0],
                'action': action,
                'price': price,
                'quantity': self.position,
                'pnl': pnl
            })
            
            self.position = 0
            print(f"[{trade_record[0]}] {action} @ ${price:.2f} | "
                  f"P&L: ${pnl:.2f} | Cash: ${self.cash:.2f} | {reason}")
    
    def read_new_csv_data(self):
        """Read only new data from CSV file"""
        if not os.path.exists(CSV_NAME):
            return []
        
        new_lines = []
        with open(CSV_NAME, 'r') as f:
            f.seek(self.last_position)
            for line in f:
                if line.strip() and not line.startswith('timestamp'):  # Skip header
                    new_lines.append(line.strip())
            self.last_position = f.tell()
        
        return new_lines
    
    def run(self):
        """Main backtesting loop"""
        print("HFT Backtester Engine Started...")
        print(f"Monitoring {CSV_NAME} for market data")
        self.init_db()
        
        # Wait for CSV to be created
        while not os.path.exists(CSV_NAME) and self.running:
            time.sleep(0.1)
        
        # Skip header initially
        with open(CSV_NAME, 'r') as f:
            self.last_position = f.tell()
        
        while self.running:
            try:
                # Read only new data from CSV
                new_data = self.read_new_csv_data()
                
                if not new_data:
                    time.sleep(0.01)
                    continue
                
                # Process each new line
                for line in new_data:
                    if not self.running:
                        break
                    
                    parts = line.split(',')
                    if len(parts) >= 4:
                        timestamp = parts[0]
                        ticker = parts[1]
                        current_price = float(parts[2])
                        volume = int(parts[3])
                        
                        # Add to price buffer
                        self.price_buffer.append(current_price)
                        
                        # Need at least 10 prices for analysis
                        if len(self.price_buffer) < 10:
                            continue
                        
                        # Calculate indicators
                        prices = list(self.price_buffer)
                        short_ma = sum(prices[-5:]) / 5
                        long_ma = sum(prices) / len(prices)
                        
                        # Trading signals
                        if self.position == 0:
                            # Entry signals
                            if current_price < short_ma * 0.9995:
                                self.execute_trade('BUY', current_price, 
                                                 f"Price below 5-MA (${short_ma:.2f})")
                            elif current_price < long_ma * 0.999:
                                self.execute_trade('BUY', current_price, 
                                                 f"Price below 10-MA (${long_ma:.2f})")
                        else:
                            # Exit signals
                            if current_price > short_ma * 1.0005:
                                self.execute_trade('SELL', current_price, 
                                                 f"Price above 5-MA (${short_ma:.2f})")
                            elif current_price > long_ma * 1.001:
                                self.execute_trade('SELL', current_price, 
                                                 f"Price above 10-MA (${long_ma:.2f})")
                        
                        # Calculate metrics every 10 ticks
                        if len(self.price_buffer) % 10 == 0:
                            sharpe, max_dd = self.calculate_metrics(prices)
                            print(f"Metrics - Sharpe: {sharpe:.2f} | Max DD: {max_dd:.2%}")
                
                time.sleep(0.01)  # Small sleep to prevent CPU hogging
                
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(0.1)
        
        self.cleanup()
    
    def cleanup(self):
        """Cleanup database connection"""
        if self.conn:
            # Calculate final performance
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT 
                    COUNT(*) as trades,
                    SUM(CASE WHEN action='BUY' THEN -price*quantity ELSE price*quantity END) as pnl
                FROM portfolio
            """)
            result = cursor.fetchone()
            print(f"\nFinal Statistics:")
            print(f"Total Trades: {result[0]}")
            print(f"Final P&L: ${result[1]:.2f}")
            print(f"Final Cash: ${self.cash:.2f}")
            
            self.conn.close()

if __name__ == "__main__":
    backtester = HFTBacktester()
    backtester.run()
