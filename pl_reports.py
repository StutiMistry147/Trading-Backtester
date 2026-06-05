import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import config

class PerformanceReporter:
    def __init__(self, db_name='hft_results.db'):
        self.conn = sqlite3.connect(db_name)

    def calculate_sharpe_ratio(self, returns):
        """Calculate annualized Sharpe ratio"""
        if len(returns) == 0 or returns.std() == 0:
            return 0
        excess_returns = returns - config.RISK_FREE_RATE/252
        return np.sqrt(252) * excess_returns.mean() / returns.std()

    def calculate_calmar_ratio(self, annualized_return, max_drawdown):
        """
        Calculate Calmar ratio = Annualized Return / Absolute Max Drawdown
        Both inputs should be in the same format (decimal, not percentage)
        """
        if max_drawdown == 0:
            return float('inf') if annualized_return > 0 else 0
        
        # Ensure both are in decimal form (not percentage)
        max_dd_abs = abs(max_drawdown)  # Convert to positive for division
        
        if max_dd_abs == 0:
            return float('inf') if annualized_return > 0 else 0
            
        return annualized_return / max_dd_abs

    def calculate_max_drawdown(self, equity_curve):
        """Calculate maximum drawdown and return drawdown series"""
        if len(equity_curve) == 0:
            return 0, []
        
        equity_series = pd.Series(equity_curve)
        rolling_max = equity_series.cummax()
        drawdown = (equity_series - rolling_max) / rolling_max
        max_drawdown = drawdown.min()
        
        return max_drawdown, drawdown

    def calculate_annualized_return(self, total_return_pct, num_trading_days):
        """Convert total return to annualized return"""
        if num_trading_days == 0:
            return 0
        # Assuming 252 trading days per year
        years = num_trading_days / 252
        if years <= 0:
            return 0
        # Convert percentage to decimal for calculation
        total_return_decimal = total_return_pct / 100
        annualized = (1 + total_return_decimal) ** (1 / years) - 1
        return annualized

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
            ORDER BY timestamp, trade_id
        """, self.conn)

        if df.empty:
            print("No trades found in database.")
            return

        # Check which period we're reporting on
        if 'period' in df.columns:
            periods = df['period'].unique()
            period_str = f" (Period: {', '.join(periods)})"
        else:
            period_str = ""

        # Calculate trade pairs and P&L
        trades = []
        equity_curve = [config.STARTING_CASH]
        timestamps = []
        returns = []
        trade_pnls = []
        trade_dates = []  # Track dates for annualization

        position = 0
        buy_price = 0
        buy_quantity = 0
        buy_commission = 0
        buy_timestamp = None

        for _, row in df.iterrows():
            trade = {
                'timestamp': row['timestamp'],
                'action': row['action'],
                'price': row['price'],
                'quantity': row['quantity'],
                'commission': row['commission']
            }

            if row['action'] == 'BUY' and position == 0:
                position = row['quantity']
                buy_price = row['price']
                buy_quantity = row['quantity']
                buy_commission = row['commission']
                buy_timestamp = row['timestamp']
                trades.append(trade)

            elif row['action'] == 'SELL' and position > 0:
                # Calculate P&L with transaction costs
                gross_pnl = (row['price'] - buy_price) * buy_quantity
                total_commission = buy_commission + row['commission']
                net_pnl = gross_pnl - total_commission
                
                trade['pnl'] = net_pnl
                trade_pnls.append(net_pnl)
                trades.append(trade)

                # Update equity curve
                new_equity = equity_curve[-1] + net_pnl
                equity_curve.append(new_equity)
                timestamps.append(row['timestamp'])
                trade_dates.append(row['timestamp'])  # Store for annualization

                # Calculate return
                if len(equity_curve) > 1:
                    ret = (equity_curve[-1] - equity_curve[-2]) / equity_curve[-2]
                    returns.append(ret)

                position = 0

        # Calculate metrics
        total_trades = len(df)
        buy_trades = len(df[df['action'] == 'BUY'])
        sell_trades = len(df[df['action'] == 'SELL'])

        # Calculate total P&L
        total_pnl = sum(trade_pnls)
        total_return_pct = (total_pnl / config.STARTING_CASH) * 100
        
        # Calculate annualized return (estimate trading days from timestamps)
        if trade_dates:
            # This is a simplification - in reality you'd parse actual dates
            # For now, we'll assume each trade represents roughly one trading day
            num_trading_days = len(trade_dates)
        else:
            num_trading_days = 0
        
        annualized_return = self.calculate_annualized_return(total_return_pct, num_trading_days)

        # Calculate returns for Sharpe ratio
        returns_series = pd.Series(returns)
        sharpe = self.calculate_sharpe_ratio(returns_series)
        
        # Calculate max drawdown and get drawdown series
        max_dd, drawdown_series = self.calculate_max_drawdown(equity_curve)
        
        # Calculate Calmar ratio (using annualized return and max drawdown, both in decimal)
        calmar = self.calculate_calmar_ratio(annualized_return, max_dd)
        
        win_rate = self.calculate_win_rate(trades)

        # Calculate additional metrics
        winning_trades = [pnl for pnl in trade_pnls if pnl > 0]
        losing_trades = [pnl for pnl in trade_pnls if pnl < 0]

        avg_win = np.mean(winning_trades) if winning_trades else 0
        avg_loss = np.mean(losing_trades) if losing_trades else 0
        profit_factor = abs(sum(winning_trades) / sum(losing_trades)) if losing_trades and sum(losing_trades) != 0 else float('inf')
        
        # Calculate total commission
        total_commission = df['commission'].sum() if 'commission' in df.columns else 0

        # Print report
        print("\n" + "="*80)
        print(f"HIGH-FREQUENCY TRADING BACKTEST RESULTS{period_str}")
        print("="*80)
        print(f"Strategy: {config.SHORT_MA_WINDOW}/{config.LONG_MA_WINDOW} MA Crossover")
        print(f"Transaction Costs: {config.COMMISSION_RATE:.2%} commission + {config.SLIPPAGE:.2%} slippage per trade")

        print(f"\n{'TRADING SUMMARY':^80}")
        print("-"*80)
        print(f"{'Total Trades:':<35} {total_trades}")
        print(f"{'Buy Trades:':<35} {buy_trades}")
        print(f"{'Sell Trades:':<35} {sell_trades}")
        print(f"{'Complete Rounds:':<35} {len(trades)//2}")
        print(f"{'Total Commission Paid:':<35} ${total_commission:,.2f}")

        print(f"\n{'PERFORMANCE METRICS':^80}")
        print("-"*80)
        print(f"{'Net P&L:':<35} ${total_pnl:,.2f}")
        print(f"{'Total Return:':<35} {total_return_pct:.2f}%")
        print(f"{'Annualized Return:':<35} {annualized_return:.2%}")
        print(f"{'Sharpe Ratio:':<35} {sharpe:.3f}")
        print(f"{'Calmar Ratio:':<35} {calmar:.3f}")
        print(f"{'Max Drawdown:':<35} {max_dd:.2%}")
        print(f"{'Win Rate:':<35} {win_rate:.1%}")
        print(f"{'Profit Factor:':<35} {profit_factor:.2f}")
        print(f"{'Avg Win:':<35} ${avg_win:,.2f}")
        print(f"{'Avg Loss:':<35} ${avg_loss:,.2f}")

        print(f"\n{'CALMAR RATIO CALCULATION DETAILS':^80}")
        print("-"*80)
        print(f"Annualized Return: {annualized_return:.2%} (as decimal: {annualized_return:.4f})")
        print(f"Max Drawdown: {max_dd:.2%} (as decimal: {abs(max_dd):.4f})")
        print(f"Calmar = Annualized Return / |Max Drawdown| = {annualized_return:.4f} / {abs(max_dd):.4f} = {calmar:.3f}")

        print(f"\n{'CONFIGURATION':^80}")
        print("-"*80)
        print(f"{'Commission Rate:':<35} {config.COMMISSION_RATE:.3%}")
        print(f"{'Slippage:':<35} {config.SLIPPAGE:.3%}")
        print(f"{'MA Windows:':<35} {config.SHORT_MA_WINDOW}/{config.LONG_MA_WINDOW}")
        print(f"{'Signal Thresholds:':<35} Buy: {config.BUY_SHORT_MA_THRESHOLD:.4f}/{config.BUY_LONG_MA_THRESHOLD:.3f}, "
              f"Sell: {config.SELL_SHORT_MA_THRESHOLD:.4f}/{config.SELL_LONG_MA_THRESHOLD:.3f}")
        print(f"{'Starting Capital:':<35} ${config.STARTING_CASH:,.0f}")
        print("="*80)

        # Create plots with drawdown curve
        if len(equity_curve) > 1:
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), 
                                           gridspec_kw={'height_ratios': [2, 1]})
            
            x_labels = range(len(equity_curve[1:]))

            # Plot 1: Equity Curve
            ax1.plot(x_labels, equity_curve[1:], 'b-', linewidth=2, label='Equity Curve')
            ax1.axhline(y=equity_curve[0], color='r', linestyle='--', label='Initial Capital', alpha=0.7)
            
            ax1.fill_between(x_labels, equity_curve[0], equity_curve[1:], 
                            where=np.array(equity_curve[1:]) >= equity_curve[0], 
                            color='g', alpha=0.3, label='Profit')
            ax1.fill_between(x_labels, equity_curve[0], equity_curve[1:], 
                            where=np.array(equity_curve[1:]) < equity_curve[0], 
                            color='r', alpha=0.3, label='Loss')
            
            ax1.set_xlabel('Trade Number')
            ax1.set_ylabel('Portfolio Value ($)')
            ax1.set_title(f'HFT Backtest Equity Curve{period_str} (with Transaction Costs)')
            ax1.legend(loc='best')
            ax1.grid(True, alpha=0.3)
            
            # Add text box with key metrics
            textstr = f'Sharpe: {sharpe:.2f} | Calmar: {calmar:.2f} | Win Rate: {win_rate:.1%}\n'
            textstr += f'Total Return: {total_return_pct:.1f}% | Max DD: {max_dd:.2%}'
            props = dict(boxstyle='round', facecolor='wheat', alpha=0.8)
            ax1.text(0.02, 0.98, textstr, transform=ax1.transAxes, fontsize=9,
                    verticalalignment='top', bbox=props)

            # Plot 2: Drawdown Curve
            if len(drawdown_series) > 1:
                drawdown_values = drawdown_series[1:] * 100
                ax2.fill_between(x_labels, 0, drawdown_values, color='red', alpha=0.5)
                ax2.plot(x_labels, drawdown_values, 'r-', linewidth=1.5)
                ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
                
                # Highlight max drawdown
                min_idx = np.argmin(drawdown_values) if len(drawdown_values) > 0 else 0
                if min_idx < len(x_labels):
                    ax2.plot(x_labels[min_idx], drawdown_values[min_idx], 'ro', markersize=8, 
                            label=f'Max DD: {drawdown_values[min_idx]:.1f}%')
                
                ax2.set_xlabel('Trade Number')
                ax2.set_ylabel('Drawdown (%)')
                ax2.set_title('Drawdown Curve')
                ax2.legend(loc='best')
                ax2.grid(True, alpha=0.3)
                ax2.set_ylim(bottom=max(drawdown_values.min() * 1.1 if drawdown_values.min() < 0 else -1, -50), 
                            top=5)
            
            plt.tight_layout()
            plt.savefig('equity_curve_with_drawdown.png', dpi=300, bbox_inches='tight')
            plt.show()
            print("\n✓ Equity curve with drawdown saved as 'equity_curve_with_drawdown.png'")
        else:
            print("\n⚠ Insufficient trades for meaningful equity curve (need at least 2 trades)")

        return {
            'total_trades': total_trades,
            'net_pnl': total_pnl,
            'total_return_pct': total_return_pct,
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe,
            'calmar_ratio': calmar,
            'max_drawdown': max_dd,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_commission': total_commission
        }

    def compare_periods(self):
        """Compare in-sample vs out-of-sample results if both databases exist"""
        import os
        
        results = {}
        for period, db in [('IN-SAMPLE', 'hft_results_in_sample.db'), 
                          ('OUT-OF-SAMPLE', 'hft_results_out_sample.db')]:
            if os.path.exists(db):
                self.conn = sqlite3.connect(db)
                results[period] = self.generate_report()
                self.conn.close()
        
        if len(results) == 2:
            print("\n" + "="*80)
            print("IN-SAMPLE vs OUT-OF-SAMPLE COMPARISON")
            print("="*80)
            print(f"{'Metric':<30} {'In-Sample':<20} {'Out-of-Sample':<20} {'Change':<15}")
            print("-"*85)
            
            for metric in ['sharpe_ratio', 'calmar_ratio', 'total_return_pct', 'max_drawdown', 'win_rate']:
                in_val = results['IN-SAMPLE'][metric]
                out_val = results['OUT-OF-SAMPLE'][metric]
                
                if metric == 'max_drawdown':
                    change = out_val - in_val
                    print(f"{metric.replace('_', ' ').title():<30} {in_val:<+20.2%} {out_val:<+20.2%} {change:+15.2%}")
                elif metric in ['sharpe_ratio', 'calmar_ratio']:
                    change = out_val - in_val
                    print(f"{metric.replace('_', ' ').title():<30} {in_val:<+20.3f} {out_val:<+20.3f} {change:+15.3f}")
                else:
                    change = out_val - in_val
                    print(f"{metric.replace('_', ' ').title():<30} {in_val:<+20.2f} {out_val:<+20.2f} {change:+15.2f}")

    def close(self):
        self.conn.close()

if __name__ == "__main__":
    reporter = PerformanceReporter()
    reporter.generate_report()

    print("\n" + "="*80)
    compare = input("Compare in-sample vs out-of-sample results? (y/n): ").lower()
    if compare == 'y':
        reporter.compare_periods()
    
    reporter.close()
