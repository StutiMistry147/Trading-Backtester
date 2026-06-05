# config.py
# Trading strategy parameters
SHORT_MA_WINDOW = 5
LONG_MA_WINDOW = 10

#Signal thresholds
BUY_SHORT_MA_THRESHOLD = 0.9995
BUY_LONG_MA_THRESHOLD = 0.999
SELL_SHORT_MA_THRESHOLD = 1.0005
SELL_LONG_MA_THRESHOLD = 1.001

#Transaction costs
COMMISSION_RATE = 0.001
SLIPPAGE = 0.0002

#Walk-forward validation
TRAIN_RATIO = 0.7

# Strategy quality thresholds (for walk-forward validation)
SHARPE_DIFF_GOOD = 0.2    # Difference <= 0.2 -> GOOD
SHARPE_DIFF_MODERATE = 0.5  # Difference <= 0.5 -> MODERATE
MIN_OUT_OF_SAMPLE_SHARPE = 0.0  # Must be > 0 to be considered viable

# Trading parameters
STARTING_CASH = 100000
TRADE_QUANTITY = 100

# Risk-free rate for Sharpe calculation (annualized)
RISK_FREE_RATE = 0.02

# Performance reporting
PRICE_BUFFER_SIZE = 50
