# Polymarket Trading Bot
Automated trading system for Polymarket prediction markets.

## Features

- **Arbitrage Engine**: Detects cross-market arbitrage opportunities
- **Mispricing Engine**: Compares Polymarket prices to external probability models
- **Microstructure Engine**: Analyzes order book for short-term signals
- **Risk Management**: Position limits, stop losses, drawdown protection
- **Real-time Monitoring**: Prometheus metrics, health checks, logging

## Quick Start

### Local Development

```bash
# Clone and install
git clone https://github.com/yourusername/polymarket-bot.git
cd polymarket-bot
pip install -r requirements.txt

# Configure
cp config.yaml.example config.yaml
# Edit config.yaml with your API keys

# Run
python -m polymarket_bot.main
```

### Docker

```bash
# Build
docker build -t polymarket-bot .

# Run
docker run -d \
  -e POLYMARKET_API_KEY="$API_KEY" \
  -e POLYMARKET_PRIVATE_KEY="$PRIVATE_KEY" \
  -e LOG_LEVEL="INFO" \
  --name polymarket-bot \
  polymarket-bot
```

### Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login
railway login

# Init project
railway init

# Set environment variables
railway variables set POLYMARKET_API_KEY="your_key"
railway variables set POLYMARKET_PRIVATE_KEY="your_key"

# Deploy
railway up
```

## Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `POLYMARKET_API_KEY` | Yes | Polymarket CLOB API key |
| `POLYMARKET_PRIVATE_KEY` | Yes | Private key for signing orders |
| `ENABLE_ARB` | No | Enable arbitrage strategy (default: true) |
| `ENABLE_MISPRICING` | No | Enable mispricing strategy (default: true) |
| `ENABLE_MICRO` | No | Enable microstructure strategy (default: true) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |
| `PAPER_TRADING` | No | Paper trading mode (default: false) |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Polymarket Trading Bot                   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Data Layer  │  │ Strategies  │  │ Risk Management     │  │
│  │ - WebSocket │  │ - Arb       │  │ - Position Limits   │  │
│  │ - REST API  │  │ - Misprice  │  │ - Stop Losses       │  │
│  │ - External  │  │ - Micro     │  │ - Drawdown Limit    │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
│         │                │                     │             │
│         └────────────────┼─────────────────────┘             │
│                          ▼                                   │
│                 ┌─────────────────┐                          │
│                 │ Execution Layer │                          │
│                 │ - Order Manager │                          │
│                 │ - Fill Tracking │                          │
│                 └─────────────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/metrics` | GET | Prometheus metrics |
| `/portfolio` | GET | Current portfolio |
| `/positions` | GET | Open positions |
| `/kill` | POST | Trigger kill switch |
| `/stop` | POST | Stop bot gracefully |

## Backtesting

```python
from polymarket_bot.backtest import BacktestEngine, HistoricalData

# Load historical data
data = HistoricalData.from_csv("historical_data.csv")

# Create strategy
def my_strategy(snapshot):
    # Your signal generation logic
    return signals

# Run backtest
engine = BacktestEngine()
result = engine.run(data, my_strategy)

print(f"Return: {result.total_return:.2%}")
print(f"Sharpe: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
```

## Risk Warning

⚠️ **This software trades real capital.** 

- Start with paper trading mode
- Never risk more than you can afford to lose
- Understand all strategies before deploying
- Monitor bot activity continuously

## License

MIT License - see LICENSE file.
