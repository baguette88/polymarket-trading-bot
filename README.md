# Polymarket Trading Bot Framework

A production-grade framework for building automated trading bots on Polymarket. This is a **stripped and improved** version of a real trading system, open-sourced for educational purposes.

**What's different from production:**
- No specific strategies or signals (you build your own)
- No proprietary thresholds or alpha
- Better modular architecture (production code is more monolithic)
- Educational comments and documentation

**This is not a get-rich-quick scheme.** Trading is hard. Most strategies lose money. This framework helps you build properly if you decide to try.

## What This Repo Provides

- Wallet setup and authentication with py-clob-client
- Order execution with proper error handling
- State management and trade logging
- Position tracking and P&L reconciliation
- Technical indicators library (RSI, Stochastic, Bollinger, etc.)
- Signal framework (bring your own logic)
- Dashboard template (Streamlit)
- Deployment guides for 24/7 operation

## What This Repo Does NOT Provide

- Profitable strategies (you must develop and validate your own)
- Backtesting data (Polymarket historical data is limited)
- Financial advice (this is educational/research software)

## Quick Start

```bash
# Clone
git clone https://github.com/baguette88/polymarket-trading-bot.git
cd polymarket-trading-bot

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your wallet details (see Wallet Setup below)

# Run in paper mode first
python bot.py --paper --interval 60
```

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │           TRADING BOT                   │
                    ├─────────────────────────────────────────┤
                    │                                         │
┌───────────┐       │  ┌───────────┐    ┌───────────┐        │
│  Market   │──────▶│  │   Data    │───▶│  Signal   │        │
│   Data    │       │  │  Fetcher  │    │  Engine   │        │
│ (Binance) │       │  └───────────┘    └─────┬─────┘        │
└───────────┘       │                         │               │
                    │                         ▼               │
┌───────────┐       │  ┌───────────┐    ┌───────────┐        │
│Polymarket │◀─────▶│  │   Order   │◀───│   Trade   │        │
│   CLOB    │       │  │ Executor  │    │  Manager  │        │
└───────────┘       │  └───────────┘    └─────┬─────┘        │
                    │                         │               │
                    │                   ┌─────▼─────┐         │
                    │                   │   State   │         │
                    │                   │ (JSON DB) │         │
                    │                   └───────────┘         │
                    │                                         │
                    └─────────────────────────────────────────┘
```

## Wallet Setup

### 1. Create a Dedicated Wallet

**Never use your main wallet for bot trading.**

```bash
# Generate a new wallet (or use MetaMask to create one)
# Fund it with only what you're willing to lose
```

### 2. Get Your Private Key

Export from MetaMask or your wallet provider. **Keep this secret.**

### 3. Approve USDC for Trading

Before the bot can trade, you need to approve USDC spending on Polymarket:

```python
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    key=YOUR_PRIVATE_KEY,
    chain_id=137  # Polygon mainnet
)

# This approves USDC for the exchange
client.set_allowances()
```

### 4. Configure Environment

```bash
# .env
POLYGON_WALLET_PRIVATE_KEY=0x...your_private_key...
POLYGON_RPC_URL=https://polygon-rpc.com
```

## Order Execution Best Practices

### 1. Always Check the Orderbook First

```python
def get_orderbook(client, token_id):
    """Fetch orderbook and calculate effective prices."""
    book = client.get_order_book(token_id)

    best_bid = float(book['bids'][0]['price']) if book['bids'] else 0
    best_ask = float(book['asks'][0]['price']) if book['asks'] else 1

    return {
        'bid': best_bid,
        'ask': best_ask,
        'spread': best_ask - best_bid,
        'mid': (best_bid + best_ask) / 2
    }
```

### 2. Use Market Orders Carefully

Polymarket uses a CLOB (Central Limit Order Book). "Market orders" are really aggressive limit orders:

```python
def place_market_buy(client, token_id, amount_usd, max_price=0.99):
    """
    Place a market buy order.

    IMPORTANT: Always set a max_price to avoid getting filled at terrible prices.
    """
    book = get_orderbook(client, token_id)

    if book['ask'] > max_price:
        raise ValueError(f"Ask price {book['ask']} exceeds max {max_price}")

    # Calculate shares based on ask price
    shares = amount_usd / book['ask']

    order = client.create_and_post_order(
        OrderArgs(
            token_id=token_id,
            price=book['ask'],  # Match the ask
            size=shares,
            side=BUY
        )
    )
    return order
```

### 3. Handle Order Failures Gracefully

```python
def execute_with_retry(client, order_args, max_retries=3):
    """Execute order with exponential backoff."""
    for attempt in range(max_retries):
        try:
            order = client.create_and_post_order(order_args)

            if order.get('status') == 'matched':
                return order

            # Order might be pending - check status
            time.sleep(2)
            status = client.get_order(order['orderID'])
            return status

        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            logging.warning(f"Order failed, retrying in {wait}s: {e}")
            time.sleep(wait)
```

### 4. Verify Fills

```python
def verify_fill(client, order_id, timeout=30):
    """Wait for and verify order fill."""
    start = time.time()

    while time.time() - start < timeout:
        try:
            order = client.get_order(order_id)

            if order['status'] == 'MATCHED':
                return {
                    'filled': True,
                    'size': float(order['size_matched']),
                    'price': float(order['price']),
                    'tx': order.get('transactionHash')
                }
            elif order['status'] in ['CANCELLED', 'EXPIRED']:
                return {'filled': False, 'reason': order['status']}

        except Exception as e:
            logging.warning(f"Error checking order: {e}")

        time.sleep(2)

    return {'filled': False, 'reason': 'timeout'}
```

## State Management

### Why JSON Over SQLite?

For single-bot deployments, JSON state files are:
- Human-readable (easy debugging)
- Git-friendly (can track changes)
- Simple (no ORM, no migrations)
- Atomic (write temp file, then rename)

```python
import json
from pathlib import Path

STATE_FILE = Path("state.json")

def load_state():
    """Load state with defaults."""
    if STATE_FILE.exists():
        return json.load(open(STATE_FILE))
    return {
        'trades': [],
        'total_pnl': 0,
        'wins': 0,
        'losses': 0,
        'last_signal': None
    }

def save_state(state):
    """Atomic save - write to temp, then rename."""
    temp = STATE_FILE.with_suffix('.tmp')
    with open(temp, 'w') as f:
        json.dump(state, f, indent=2, default=str)
    temp.rename(STATE_FILE)
```

### Trade Record Schema

```python
trade = {
    'id': str(uuid4()),
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'market_id': 'condition_id_here',
    'token_id': 'token_id_here',
    'direction': 'long',  # or 'short'
    'outcome': 'YES',     # or 'NO'
    'entry_price': 0.48,
    'size': 10.42,        # shares
    'amount_usd': 5.0,    # cost
    'order_id': 'polymarket_order_id',
    'tx_hash': '0x...',

    # Filled after resolution
    'resolved': False,
    'result': None,       # 'win' or 'loss'
    'pnl': None,
    'exit_price': None
}
```

## P&L Reconciliation

### Automatic Resolution Tracking

```python
def check_resolution(client, trade):
    """Check if a market has resolved and calculate P&L."""
    if trade['resolved']:
        return trade

    try:
        market = client.get_market(trade['market_id'])

        if market.get('resolved'):
            winning_token = market['winning_token_id']

            if trade['token_id'] == winning_token:
                # Winner - get full payout
                pnl = trade['size'] - trade['amount_usd']
                result = 'win'
            else:
                # Loser - lose entire stake
                pnl = -trade['amount_usd']
                result = 'loss'

            trade['resolved'] = True
            trade['result'] = result
            trade['pnl'] = round(pnl, 4)

    except Exception as e:
        logging.warning(f"Resolution check failed: {e}")

    return trade
```

### Manual Reconciliation

```bash
# Check positions via API
curl "https://data-api.polymarket.com/positions?user=YOUR_WALLET"

# Check specific market
curl "https://gamma-api.polymarket.com/markets/CONDITION_ID"
```

## Signal Framework

The framework provides indicators; you provide the logic:

```python
from indicators import calculate_rsi, calculate_stochastic, calculate_bollinger_bands

class SignalEngine:
    """Override check_signal() with your strategy."""

    def __init__(self, config):
        self.config = config
        self.last_signal = None

    def calculate_indicators(self, df):
        """Calculate all indicators from OHLCV data."""
        indicators = {}
        indicators['rsi'] = calculate_rsi(df, 14).iloc[-1]
        indicators['stoch_k'], _ = calculate_stochastic(df)
        indicators['stoch_k'] = indicators['stoch_k'].iloc[-1]
        _, _, _, bb_pct = calculate_bollinger_bands(df)
        indicators['bb_percent'] = bb_pct.iloc[-1]
        return indicators

    def check_signal(self, indicators):
        """
        YOUR STRATEGY GOES HERE.

        Return: 'long', 'short', or None
        """
        # Example (NOT a recommendation):
        # if indicators['rsi'] < 30:
        #     return 'long'
        # if indicators['rsi'] > 70:
        #     return 'short'
        return None
```

## Risk Management

### Position Sizing

Never bet more than you can afford to lose. Common approaches:

```python
def fixed_size(config):
    """Fixed dollar amount per trade."""
    return config.get('bet_size', 5.0)

def percent_of_bankroll(bankroll, percent=0.02):
    """Fixed percentage of bankroll (e.g., 2%)."""
    return bankroll * percent

def kelly_criterion(win_rate, odds, fraction=0.5):
    """
    Kelly criterion for optimal bet sizing.
    Use fraction=0.5 (half-Kelly) for variance reduction.

    win_rate: your expected win probability
    odds: net odds (payout/stake - 1)
    """
    if win_rate <= 0 or odds <= 0:
        return 0

    kelly = (win_rate * odds - (1 - win_rate)) / odds
    return max(0, kelly * fraction)
```

### Hard Limits

```python
# config.json
{
    "max_bet_usd": 50,
    "max_daily_loss": 100,
    "max_open_positions": 3,
    "max_entry_price": 0.60,  # Don't buy above 60 cents
    "min_spread": 0.02        # Require 2% spread minimum
}
```

### Kill Switch

```python
def check_kill_switch(state, config):
    """Stop trading if limits exceeded."""
    if state['total_pnl'] < -config['max_daily_loss']:
        raise KillSwitchError("Daily loss limit exceeded")

    open_positions = sum(1 for t in state['trades'] if not t['resolved'])
    if open_positions >= config['max_open_positions']:
        return False  # Skip this trade

    return True
```

## Deployment

### Process Management

Use a PID lock to prevent duplicate instances:

```python
PIDFILE = Path("bot.pid")

def acquire_lock():
    if PIDFILE.exists():
        old_pid = int(PIDFILE.read_text())
        try:
            os.kill(old_pid, 0)  # Check if running
            sys.exit(f"Bot already running (PID {old_pid})")
        except ProcessLookupError:
            pass  # Stale PID file

    PIDFILE.write_text(str(os.getpid()))
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True))
```

### Systemd Service (Linux)

```ini
# /etc/systemd/system/polymarket-bot.service
[Unit]
Description=Polymarket Trading Bot
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/polymarket-bot
EnvironmentFile=/home/trader/polymarket-bot/.env
ExecStart=/home/trader/polymarket-bot/venv/bin/python bot.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### launchd (macOS)

```xml
<!-- ~/Library/LaunchAgents/com.polymarket.bot.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.polymarket.bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/venv/bin/python</string>
        <string>/path/to/bot.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/polymarket-bot.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/polymarket-bot.error.log</string>
</dict>
</plist>
```

### Monitoring

```bash
# Health check script
#!/bin/bash
HEARTBEAT_FILE="/path/to/bot/.heartbeat"
MAX_AGE=120  # seconds

if [ ! -f "$HEARTBEAT_FILE" ]; then
    echo "CRITICAL: Heartbeat file missing"
    exit 2
fi

AGE=$(($(date +%s) - $(stat -f %m "$HEARTBEAT_FILE")))
if [ $AGE -gt $MAX_AGE ]; then
    echo "CRITICAL: Heartbeat stale (${AGE}s old)"
    exit 2
fi

echo "OK: Bot healthy (heartbeat ${AGE}s ago)"
exit 0
```

## Common Pitfalls

### 1. Duplicate Trades

Always track the last market you traded to prevent double-betting:

```python
def should_trade(state, market_id):
    if state.get('last_market_id') == market_id:
        return False  # Already traded this market
    return True
```

### 2. Signal Persistence

Require signals to reset before firing again:

```python
def check_signal_with_reset(self, indicators):
    signal = self._calculate_signal(indicators)

    if signal == self.last_signal:
        return None  # Signal hasn't reset

    if signal:
        self.last_signal = signal
        return signal

    # Signal cleared - reset
    self.last_signal = None
    return None
```

### 3. Race Conditions

Markets close at specific times. Don't trade too close to expiry:

```python
def time_to_expiry(market_end_time):
    now = datetime.now(timezone.utc)
    end = datetime.fromisoformat(market_end_time)
    return (end - now).total_seconds()

# Don't trade if less than 60 seconds to expiry
if time_to_expiry(market['end_time']) < 60:
    return  # Too risky
```

### 4. API Rate Limits

Polymarket APIs have rate limits. Use caching and backoff:

```python
import time
from functools import lru_cache

@lru_cache(maxsize=100)
def get_market_cached(market_id):
    # Cache for repeated lookups within same cycle
    return client.get_market(market_id)

def api_call_with_backoff(func, *args, max_retries=3):
    for i in range(max_retries):
        try:
            return func(*args)
        except RateLimitError:
            time.sleep(2 ** i)
    raise Exception("Rate limit exceeded after retries")
```

## Testing

### Paper Trading Mode

```python
class PaperTrader:
    """Simulates trades without real execution."""

    def __init__(self):
        self.balance = 1000.0
        self.positions = []

    def execute(self, direction, amount, price):
        if amount > self.balance:
            raise InsufficientFunds()

        self.balance -= amount
        self.positions.append({
            'direction': direction,
            'amount': amount,
            'price': price,
            'timestamp': datetime.now()
        })
        return {'status': 'PAPER', 'amount': amount}
```

### Backtesting Caveats

Polymarket historical data is limited. If you backtest:
- Account for spread (you won't get mid-price)
- Account for slippage (your order affects the book)
- Be skeptical of results (overfitting is easy)
- Validate with paper trading before live

## Project Structure

This framework uses a modular architecture with clean separation of concerns - an improvement over typical monolithic trading scripts:

```
polymarket-trading-bot/
│
├── bot.py              # Main orchestrator - ties everything together
│
├── core/               # Core trading components
│   ├── __init__.py
│   ├── client.py       # Polymarket API wrapper (authentication, orders)
│   ├── data.py         # Data fetching (Binance, price feeds)
│   ├── executor.py     # Order execution with retry/verification
│   ├── state.py        # State management (trades, P&L)
│   └── risk.py         # Risk management (limits, kill switches)
│
├── strategy/           # Strategy components (customize these)
│   ├── __init__.py
│   ├── indicators.py   # Technical indicators (RSI, Stoch, BB, etc.)
│   ├── signals.py      # Signal engine interface
│   └── example.py      # Example strategy implementation
│
├── dashboard/          # Monitoring UI
│   └── app.py          # Streamlit dashboard
│
├── config/
│   ├── bot_config.json # Runtime configuration
│   └── markets.json    # Market definitions
│
├── tests/              # Test suite
│   ├── test_indicators.py
│   ├── test_executor.py
│   └── test_state.py
│
├── requirements.txt
├── .env.example
└── README.md
```

### Why This Architecture?

| Monolithic (common) | Modular (this repo) |
|---------------------|---------------------|
| Single 2000+ line file | ~200 lines per module |
| Hard to test | Each module testable |
| Hard to swap components | Easy to swap data sources, strategies |
| Changes risk breaking everything | Changes isolated to modules |
| One developer at a time | Multiple developers can work in parallel |

## Legal Disclaimer

This software is for educational and research purposes only. Trading prediction markets involves significant risk. You can lose all of your money. This is not financial advice. The authors are not responsible for any losses.

Before using this software:
1. Understand the risks of prediction market trading
2. Only trade with money you can afford to lose
3. Comply with all applicable laws in your jurisdiction
4. Verify Polymarket's terms of service

## Resources

- [Polymarket Docs](https://docs.polymarket.com/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client)
- [Gamma API](https://gamma-api.polymarket.com/)

## License

MIT - Use at your own risk.
