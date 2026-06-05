import pandas as pd
import sqlite3
import time
import os
import signal
import sys
from collections import deque
import threading
import csv
import config
import shutil  # For backing up databases

DB_NAME = 'hft_results.db'
IN_SAMPLE_DB = 'hft_results_in_sample.db'
OUT_SAMPLE_DB = 'hft_results_out_sample.db'
CSV_NAME = 'market_data.csv'

class HFTBacktester:
    def __init__(self):
        self.conn = None
        self.running = True
        self.position = 0
        self.cash = config.STARTING_CASH
        self.starting_cash = config.STARTING_CASH
        self.trades = []
        self.price_buffer = deque(maxlen=config.PRICE_BUFFER_SIZE)
        self.last_position = 0
        
        # For walk-forward validation
        self.in_sample_results = None
        self.out_sample_results = None

        signal.signal(signal.SIGINT, self.signal_handler)

    def signal_handler(self, sig, frame):
        print("\nShutting down backtester...")
        self.running = False

    def reset_state(self, db_name=None):
        """Reset backtester state for walk-forward validation"""
        self.position = 0
        self.cash = config.STARTING_CASH
        self.trades = []
        self.price_buffer.clear()
        
        # Close existing connection if any
        if self.conn:
            self.conn.close()
        
        # Initialize new database (either default or specific name)
        self.init_db(db_name)

    def init_db(self, db_name=None):
        """Initialize database with proper indexes, optionally with custom name"""
        db_path = db_name if db_name else DB_NAME
        self.conn = sqlite3.connect(db_path, timeout=10)
        cursor = self.conn.cursor()

        cursor.execute("DROP TABLE IF EXISTS portfolio")
        cursor.execute("DROP TABLE IF EXISTS daily_summary")

        cursor.execute("""
            CREATE TABLE portfolio (
                trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                action TEXT,
                price REAL,
                quantity INTEGER,
                position_after INTEGER,
                cash_after REAL,
                reason TEXT,
                commission REAL,
                slippage REAL,
                period TEXT
            )
        """)

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

        cursor.execute("CREATE INDEX idx_timestamp ON portfolio(timestamp)")
        cursor.execute("CREATE INDEX idx_action ON portfolio(action)")
        cursor.execute("CREATE INDEX idx_period ON portfolio(period)")

        self.conn.commit()
        if not db_name:
            print("Database initialized successfully")

    def calculate_metrics(self, prices):
        """Calculate trading metrics"""
        if len(prices) < 2:
            return 0, 0

        returns = pd.Series(prices).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * (252 ** 0.5) if returns.std() > 0 else 0
        max_dd = (returns.cumsum().cummax() - returns.cumsum()).max()

        return sharpe, max_dd

    def execute_trade(self, action, price, reason, period="unknown"):
        """Execute trade with position tracking and transaction costs"""
        quantity = config.TRADE_QUANTITY
        
        # Apply slippage
        if action == 'BUY':
            execution_price = price * (1 + config.SLIPPAGE)
        else:  # SELL
            execution_price = price * (1 - config.SLIPPAGE)

        # Calculate commission
        commission = execution_price * quantity * config.COMMISSION_RATE

        if action == 'BUY' and self.position == 0:
            cost = execution_price * quantity + commission
            if self.cash >= cost:
                self.cash -= cost
                self.position = quantity
                trade_record = (
                    time.strftime('%H:%M:%S'), 
                    action, 
                    execution_price, 
                    quantity, 
                    self.position, 
                    self.cash, 
                    reason,
                    commission,
                    config.SLIPPAGE,
                    period
                )

                cursor = self.conn.cursor()
                cursor.execute("""
                    INSERT INTO portfolio 
                    (timestamp, action, price, quantity, position_after, cash_after, reason, commission, slippage, period)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, trade_record)
                self.conn.commit()

                self.trades.append({
                    'timestamp': trade_record[0],
                    'action': action,
                    'price': execution_price,
                    'quantity': quantity,
                    'commission': commission,
                    'slippage': config.SLIPPAGE,
                    'period': period
                })

                print(f"[{trade_record[0]}] {action} {quantity} @ ${execution_price:.2f} (orig: ${price:.2f}) | "
                      f"Commission: ${commission:.2f} | Position: {self.position} | Cash: ${self.cash:.2f} | {reason}")

        elif action == 'SELL' and self.position > 0:
            revenue = execution_price * self.position - commission
            self.cash += revenue
            trade_record = (
                time.strftime('%H:%M:%S'), 
                action, 
                execution_price, 
                self.position, 
                0, 
                self.cash, 
                reason,
                commission,
                config.SLIPPAGE,
                period
            )

            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO portfolio 
                (timestamp, action, price, quantity, position_after, cash_after, reason, commission, slippage, period)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, trade_record)
            self.conn.commit()

            # Calculate P&L for this trade (accounting for costs)
            buy_price = self.trades[-1]['price'] if self.trades else execution_price
            gross_pnl = (execution_price - buy_price) * self.position
            total_commission = commission + (self.trades[-1].get('commission', 0) if self.trades else 0)
            net_pnl = gross_pnl - total_commission

            self.trades.append({
                'timestamp': trade_record[0],
                'action': action,
                'price': execution_price,
                'quantity': self.position,
                'pnl': net_pnl,
                'commission': commission,
                'period': period
            })

            self.position = 0
            print(f"[{trade_record[0]}] {action} @ ${execution_price:.2f} (orig: ${price:.2f}) | "
                  f"Gross P&L: ${gross_pnl:.2f} | Commission: ${commission:.2f} | Net P&L: ${net_pnl:.2f} | Cash: ${self.cash:.2f} | {reason}")

    def read_all_csv_data(self):
        """Read all data from CSV file"""
        if not os.path.exists(CSV_NAME):
            return []

        all_lines = []
        with open(CSV_NAME, 'r') as f:
            for line in f:
                if line.strip() and not line.startswith('timestamp'):
                    all_lines.append(line.strip())
        return all_lines

    def calculate_sharpe_from_trades(self):
        """Calculate Sharpe ratio from trade returns"""
        if len(self.trades) == 0:
            return 0
        
        # Extract returns from trades
        returns = []
        for trade in self.trades:
            if 'pnl' in trade and trade['pnl'] != 0:
                returns.append(trade['pnl'] / config.STARTING_CASH)
        
        if len(returns) > 1:
            returns_series = pd.Series(returns)
            sharpe = returns_series.mean() / returns_series.std() * (252 ** 0.5) if returns_series.std() > 0 else 0
        else:
            sharpe = 0
        
        return sharpe

    def run_strategy_on_data(self, data_lines, period_name, db_name=None):
        """Run the strategy on a specific dataset"""
        print(f"\n{'='*60}")
        print(f"Running strategy on {period_name} period")
        print(f"{'='*60}")
        
        # Reset with specific database name
        self.reset_state(db_name)
        
        # Process each line
        for line in data_lines:
            if not self.running:
                break

            parts = line.split(',')
            if len(parts) >= 4:
                timestamp = parts[0]
                ticker = parts[1]
                current_price = float(parts[2])
                volume = int(parts[3])

                self.price_buffer.append(current_price)

                if len(self.price_buffer) < config.LONG_MA_WINDOW:
                    continue

                # Calculate indicators
                prices = list(self.price_buffer)
                short_ma = sum(prices[-config.SHORT_MA_WINDOW:]) / config.SHORT_MA_WINDOW
                long_ma = sum(prices) / len(prices)

                # Trading signals with configurable thresholds
                if self.position == 0:
                    if current_price < short_ma * config.BUY_SHORT_MA_THRESHOLD:
                        self.execute_trade('BUY', current_price, 
                                         f"Price below {config.SHORT_MA_WINDOW}-MA (${short_ma:.2f})",
                                         period_name)
                    elif current_price < long_ma * config.BUY_LONG_MA_THRESHOLD:
                        self.execute_trade('BUY', current_price, 
                                         f"Price below {config.LONG_MA_WINDOW}-MA (${long_ma:.2f})",
                                         period_name)
                else:
                    if current_price > short_ma * config.SELL_SHORT_MA_THRESHOLD:
                        self.execute_trade('SELL', current_price, 
                                         f"Price above {config.SHORT_MA_WINDOW}-MA (${short_ma:.2f})",
                                         period_name)
                    elif current_price > long_ma * config.SELL_LONG_MA_THRESHOLD:
                        self.execute_trade('SELL', current_price, 
                                         f"Price above {config.LONG_MA_WINDOW}-MA (${long_ma:.2f})",
                                         period_name)

        # Calculate final metrics
        final_cash = self.cash
        total_pnl = final_cash - config.STARTING_CASH
        total_return_pct = (total_pnl / config.STARTING_CASH) * 100
        sharpe = self.calculate_sharpe_from_trades()
        
        # Calculate max drawdown from equity curve
        equity_curve = [config.STARTING_CASH]
        for trade in self.trades:
            if 'pnl' in trade:
                equity_curve.append(equity_curve[-1] + trade['pnl'])
        
        if len(equity_curve) > 1:
            equity_series = pd.Series(equity_curve)
            rolling_max = equity_series.cummax()
            drawdown = (equity_series - rolling_max) / rolling_max
            max_dd = drawdown.min()
        else:
            max_dd = 0
        
        print(f"\n{period_name} Results:")
        print(f"  Total Trades: {len([t for t in self.trades if t['action'] == 'BUY'])} buys, "
              f"{len([t for t in self.trades if t['action'] == 'SELL'])} sells")
        print(f"  Total P&L: ${total_pnl:.2f} ({total_return_pct:.2f}%)")
        print(f"  Sharpe Ratio: {sharpe:.3f}")
        print(f"  Max Drawdown: {max_dd:.2%}")
        print(f"  Final Cash: ${self.cash:.2f}")
        
        return {
            'period': period_name,
            'trades': len(self.trades),
            'pnl': total_pnl,
            'return_pct': total_return_pct,
            'sharpe': sharpe,
            'max_drawdown': max_dd,
            'final_cash': self.cash,
            'db_file': db_name if db_name else DB_NAME
        }

    def run(self):
        """Main backtesting loop with walk-forward validation"""
        print("HFT Backtester Engine Started with Walk-Forward Validation...")
        print(f"Monitoring {CSV_NAME} for market data")
        
        # Wait for CSV to be created and accumulate data
        while not os.path.exists(CSV_NAME) and self.running:
            time.sleep(0.1)
        
        # Read ALL data first for walk-forward validation
        print("Reading all market data...")
        all_data = self.read_all_csv_data()
        
        if len(all_data) == 0:
            print("No data found in CSV file")
            return
        
        print(f"Total data points: {len(all_data)}")
        
        # Split data for walk-forward validation
        split_idx = int(len(all_data) * config.TRAIN_RATIO)
        in_sample_data = all_data[:split_idx]
        out_sample_data = all_data[split_idx:]
        
        print(f"In-sample data points: {len(in_sample_data)} ({config.TRAIN_RATIO*100:.0f}%)")
        print(f"Out-of-sample data points: {len(out_sample_data)} ({(1-config.TRAIN_RATIO)*100:.0f}%)")
        
        # Run on in-sample data (save to separate DB)
        self.in_sample_results = self.run_strategy_on_data(in_sample_data, "IN-SAMPLE", IN_SAMPLE_DB)
        
        # Run on out-of-sample data (save to separate DB)
        self.out_sample_results = self.run_strategy_on_data(out_sample_data, "OUT-OF-SAMPLE", OUT_SAMPLE_DB)
        
        # Print walk-forward validation summary
        print("\n" + "="*70)
        print("WALK-FORWARD VALIDATION SUMMARY")
        print("="*70)
        print(f"{'Metric':<25} {'In-Sample':<18} {'Out-of-Sample':<18} {'Difference':<15}")
        print("-"*76)
        print(f"{'Sharpe Ratio':<25} {self.in_sample_results['sharpe']:<18.3f} "
              f"{self.out_sample_results['sharpe']:<18.3f} "
              f"{self.out_sample_results['sharpe'] - self.in_sample_results['sharpe']:<+15.3f}")
        print(f"{'Total P&L':<25} ${self.in_sample_results['pnl']:<17,.2f} "
              f"${self.out_sample_results['pnl']:<17,.2f} "
              f"${self.out_sample_results['pnl'] - self.in_sample_results['pnl']:<+14,.2f}")
        print(f"{'Return %':<25} {self.in_sample_results['return_pct']:<17.2f}% "
              f"{self.out_sample_results['return_pct']:<17.2f}% "
              f"{self.out_sample_results['return_pct'] - self.in_sample_results['return_pct']:<+15.2f}%")
        print(f"{'Max Drawdown':<25} {self.in_sample_results['max_drawdown']:<17.2%} "
              f"{self.out_sample_results['max_drawdown']:<17.2%} "
              f"{self.out_sample_results['max_drawdown'] - self.in_sample_results['max_drawdown']:<+15.2%}")
        print(f"{'Total Trades':<25} {self.in_sample_results['trades']:<18} "
              f"{self.out_sample_results['trades']:<18} "
              f"{self.out_sample_results['trades'] - self.in_sample_results['trades']:<+15}")
        
        print(f"\n{'Strategy Quality Assessment':^70}")
        print("-"*70)
        
        # Evaluate strategy quality (using configurable thresholds)
        sharpe_diff = abs(self.out_sample_results['sharpe'] - self.in_sample_results['sharpe'])
        out_sample_positive = self.out_sample_results['sharpe'] > config.MIN_OUT_OF_SAMPLE_SHARPE
        
        if sharpe_diff <= config.SHARPE_DIFF_GOOD and out_sample_positive:
            quality = "GOOD ✓"
            explanation = "Strategy appears robust with consistent performance"
        elif sharpe_diff <= config.SHARPE_DIFF_MODERATE and out_sample_positive:
            quality = "MODERATE ⚠"
            explanation = "Some curve-fitting possible; consider walk-forward optimization"
        elif not out_sample_positive:
            quality = "POOR ✗"
            explanation = "Strategy fails on unseen data - likely overfit"
        else:
            quality = "WARNING ⚠"
            explanation = "High performance variation; validate with more data"
        
        print(f"Quality Rating: {quality}")
        print(f"Assessment: {explanation}")
        print(f"Sharpe Difference: {sharpe_diff:.3f} (Thresholds: Good≤{config.SHARPE_DIFF_GOOD}, Moderate≤{config.SHARPE_DIFF_MODERATE})")
        print(f"Out-of-Sample Sharpe Positive: {out_sample_positive}")
        
        print("\n" + "="*70)
        print(f"Detailed results saved to:")
        print(f"  In-sample database: {IN_SAMPLE_DB}")
        print(f"  Out-of-sample database: {OUT_SAMPLE_DB}")
        print("="*70)
        
        # Keep the out-of-sample database as the main one for reporting
        # (copy it to DB_NAME for compatibility with pl_reports.py)
        if os.path.exists(OUT_SAMPLE_DB):
            shutil.copy(OUT_SAMPLE_DB, DB_NAME)
            print(f"\nCopied out-of-sample results to {DB_NAME} for reporting")
        
        self.cleanup()

    def cleanup(self):
        """Cleanup database connection"""
        if self.conn:
            self.conn.close()

if __name__ == "__main__":
    backtester = HFTBacktester()
    backtester.run()
