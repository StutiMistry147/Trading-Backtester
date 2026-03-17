import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

class PerformanceReporter:
    def __init__(self, db_name='hft_results.db'):
        self.conn = sqlite3.connect(db_name)
        
    def calculate_sharpe_ratio(self, returns, risk_free_rate=0.02):
        """Calculate annualized Sharpe ratio"""
        if len(returns) == 0 or returns.std() == 0:
            return 0
        excess_returns = returns - risk_free_rate/252  # Daily risk-free rate
        return np.sqrt(252) * excess_returns.mean() / returns.std()
    
    def calculate_max_drawdown(self, equity_curve):
        """Calculate maximum drawdown"""
        if len(equity_curve) == 0:
            return 0
        rolling_max = pd.Series(equity_curve).cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        return drawdown.min()
    
    def calculate_win_rate(self, trades):
        """Calculate win rate from paired trades"""
        if len(trades) < 2:
            return 0
        
        wins = 0
        total = 0
        
        for i in range(0, len(trades)-1, 2):
            if i+1 < len(trades):
                buy_trade = trades[i]
                sell_trade = trades[i+1]
                if buy_trade['action'] == 'BUY' and sell_trade['action'] == 'SELL':
                    pnl = (sell_trade['price'] - buy_trade['price']) * buy_trade['quantity']
                    if pnl > 0:
                        wins += 1
                    total += 1
        
        return wins / total if total > 0 else 0
    
    def generate_report(self):
        """Generate comprehensive performance report"""
        # Load data
        df = pd.read_sql_query("""
            SELECT * FROM portfolio 
            ORDER BY timestamp
        """, self.conn)
        
        if df.empty:
            print("No trades found in database.")
            return
        
        # Calculate trade pairs and P&L
        trades = []
        equity_curve = [100000]  # Starting capital
        timestamps = []
        returns = []
        
        position = 0
        buy_price = 0
        buy_quantity = 0
        
        for _, row in df.iterrows():
            trade = {
                'timestamp': row['timestamp'],
                'action': row['action'],
                'price': row['price'],
                'quantity': row['quantity']
            }
            
            if row['action'] == 'BUY' and position == 0:
                position = row['quantity']
                buy_price = row['price']
                buy_quantity = row['quantity']
                trades.append(trade)
                
            elif row['action'] == 'SELL' and position > 0:
                pnl = (row['price'] - buy_price) * buy_quantity
                trade['pnl'] = pnl
                trades.append(trade)
                
                # Update equity curve
                new_equity = equity_curve[-1] + pnl
                equity_curve.append(new_equity)
                timestamps.append(row['timestamp'])
                
                # Calculate return
                if len(equity_curve) > 1:
                    returns.append((equity_curve[-1] - equity_curve[-2]) / equity_curve[-2])
                
                position = 0
        
        # Calculate metrics
        total_trades = len(df)
        buy_trades = len(df[df['action'] == 'BUY'])
        sell_trades = len(df[df['action'] == 'SELL'])
        
        # Calculate P&L properly (FIFO matching)
        total_pnl = sum([t.get('pnl', 0) for t in trades if 'pnl' in t])
        
        # Calculate returns for Sharpe ratio
        returns = pd.Series(returns)
        sharpe = self.calculate_sharpe_ratio(returns)
        max_dd = self.calculate_max_drawdown(equity_curve)
        win_rate = self.calculate_win_rate(trades)
        
        # Calculate additional metrics
        winning_trades = [t['pnl'] for t in trades if 'pnl' in t and t['pnl'] > 0]
        losing_trades = [t['pnl'] for t in trades if 'pnl' in t and t['pnl'] < 0]
        
        avg_win = np.mean(winning_trades) if winning_trades else 0
        avg_loss = np.mean(losing_trades) if losing_trades else 0
        profit_factor = abs(sum(winning_trades) / sum(losing_trades)) if losing_trades else float('inf')
        
        # Print report
        print("\n" + "="*60)
        print("HIGH-FREQUENCY TRADING BACKTEST RESULTS")
        print("="*60)
        
        print(f"\nTRADING SUMMARY")
        print(f"{'Total Trades:':<20} {total_trades}")
        print(f"{'Buy Trades:':<20} {buy_trades}")
        print(f"{'Sell Trades:':<20} {sell_trades}")
        print(f"{'Complete Rounds:':<20} {len(trades)//2}")
        
        print(f"\nPERFORMANCE METRICS")
        print(f"{'Net P&L:':<20} ${total_pnl:,.2f}")
        print(f"{'Sharpe Ratio:':<20} {sharpe:.3f}")
        print(f"{'Max Drawdown:':<20} {max_dd:.2%}")
        print(f"{'Win Rate:':<20} {win_rate:.1%}")
        print(f"{'Profit Factor:':<20} {profit_factor:.2f}")
        print(f"{'Avg Win:':<20} ${avg_win:,.2f}")
        print(f"{'Avg Loss:':<20} ${avg_loss:,.2f}")
        
        print(f"\nTRADE FREQUENCY")
        if not trades:
            print(f"{'Trades/Minute:':<20} N/A")
        else:
            # FIXED: Proper timestamp handling for time-only strings
            # Add a dummy date to make datetime operations work
            base_date = datetime.now().date()
            timestamps_dt = []
            for t in trades:
                if 'timestamp' in t:
                    time_str = t['timestamp']
                    if '.' in time_str:
                        # Handle HH:MM:SS.sss format
                        time_part = time_str.split('.')[0]
                    else:
                        time_part = time_str
                    dt = datetime.combine(base_date, datetime.strptime(time_part, '%H:%M:%S').time())
                    timestamps_dt.append(dt)
            
            if timestamps_dt:
                # Calculate minutes from first trade
                minutes = [(ts - timestamps_dt[0]).total_seconds() / 60.0 for ts in timestamps_dt]
                if len(minutes) > 1 and minutes[-1] > 0:
                    trades_per_minute = len(trades) / minutes[-1]
                    print(f"{'Trades/Minute:':<20} {trades_per_minute:.2f}")
                else:
                    print(f"{'Trades/Minute:':<20} N/A")
        
        print("="*60)
        
        # Plot equity curve
        if len(equity_curve) > 1:
            plt.figure(figsize=(12, 6))
            
            # Create x-axis labels (trade numbers or timestamps)
            x_labels = range(len(equity_curve[1:]))
            
            plt.plot(x_labels, equity_curve[1:], 'b-', linewidth=2, label='Equity Curve')
            plt.axhline(y=equity_curve[0], color='r', linestyle='--', label='Initial Capital')
            plt.fill_between(x_labels, equity_curve[0], equity_curve[1:], 
                            where=np.array(equity_curve[1:]) >= equity_curve[0], 
                            color='g', alpha=0.3, label='Above Capital')
            plt.fill_between(x_labels, equity_curve[0], equity_curve[1:], 
                            where=np.array(equity_curve[1:]) < equity_curve[0], 
                            color='r', alpha=0.3, label='Below Capital')
            plt.xlabel('Trade Number')
            plt.ylabel('Portfolio Value ($)')
            plt.title('HFT Backtest Equity Curve')
            plt.legend()
            plt.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig('equity_curve.png', dpi=300, bbox_inches='tight')
            plt.show()
            print("\nEquity curve saved as 'equity_curve.png'")
        
        return {
            'total_trades': total_trades,
            'net_pnl': total_pnl,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'profit_factor': profit_factor
        }
    
    def close(self):
        self.conn.close()

if __name__ == "__main__":
    reporter = PerformanceReporter()
    reporter.generate_report()
    reporter.close()
