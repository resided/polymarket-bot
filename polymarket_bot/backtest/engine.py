"""
Backtesting framework for strategy validation.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    initial_capital: float = 100000
    fee_per_transaction: float = 0.001
    slippage_model: str = "fixed"  # "fixed", "linear", "volume"
    fixed_slippage: float = 0.002  # 20 bps
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class BacktestResult:
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    hit_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    num_trades: int
    avg_trade_duration: float
    equity_curve: List[float]
    drawdown_curve: List[float]
    trade_log: List[dict]


@dataclass
class SimulatedOrder:
    market_id: str
    side: str
    size: float
    price: float
    timestamp: float
    fill_price: float = 0
    filled: bool = False
    fees: float = 0


class BacktestEngine:
    """
    Backtesting engine for strategy validation.
    
    Features:
    - Realistic slippage modeling
    - Fee simulation
    - Walk-forward validation
    - Performance metrics
    """
    
    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.capital = self.config.initial_capital
        self.positions: Dict[str, dict] = {}
        self.trades: List[dict] = []
        self.equity_curve: List[float] = [self.capital]
        self.orders: List[SimulatedOrder] = []
    
    def run(self, data: 'HistoricalData', strategy: Callable) -> BacktestResult:
        """
        Run backtest over historical data.
        
        Args:
            data: Historical market data
            strategy: Strategy function that receives market updates
        """
        self.capital = self.config.initial_capital
        self.positions = {}
        self.trades = []
        self.equity_curve = [self.capital]
        self.orders = []
        
        # Process each data point
        for timestamp, snapshot in data.stream():
            # Update strategy with new data
            signals = strategy(snapshot)
            
            # Process signals into orders
            for signal in signals:
                order = self.create_order(signal, snapshot)
                self.orders.append(order)
            
            # Simulate order execution
            for order in self.orders:
                if not order.filled:
                    self.simulate_execution(order, snapshot)
            
            # Update position values
            self.update_positions(snapshot)
            
            # Record equity
            self.equity_curve.append(self.capital + self.position_value(snapshot))
        
        return self.generate_results()
    
    def create_order(self, signal, snapshot) -> SimulatedOrder:
        """Create simulated order from signal."""
        return SimulatedOrder(
            market_id=signal.get("market_id"),
            side=signal.get("side"),
            size=signal.get("size", 0),
            price=signal.get("limit_price", snapshot.get("mid_price", 0.5)),
            timestamp=snapshot.get("timestamp", 0)
        )
    
    def simulate_execution(self, order: SimulatedOrder, snapshot):
        """Simulate order execution against order book."""
        mid_price = snapshot.get("mid_price", 0.5)
        
        if order.side == "BUY":
            fill_price = self._calculate_slippage(
                mid_price, order.size, "BUY", snapshot
            )
        else:
            fill_price = self._calculate_slippage(
                mid_price, order.size, "SELL", snapshot
            )
        
        fees = order.size * fill_price * self.config.fee_per_transaction
        
        order.fill_price = fill_price
        order.fees = fees
        order.filled = True
        
        # Update capital
        if order.side == "BUY":
            self.capital -= order.size * fill_price + fees
        else:
            self.capital += order.size * fill_price - fees
        
        # Record trade
        self.trades.append({
            "market_id": order.market_id,
            "side": order.side,
            "size": order.size,
            "entry_price": fill_price,
            "fees": fees,
            "timestamp": order.timestamp
        })
    
    def _calculate_slippage(self, mid_price: float, size: float,
                           side: str, snapshot) -> float:
        """Calculate execution price with slippage."""
        if self.config.slippage_model == "fixed":
            slippage = self.config.fixed_slippage
        elif self.config.slippage_model == "linear":
            # Slippage proportional to size
            depth = snapshot.get("depth", 10000)
            slippage = min(0.02, size / depth * 0.5)
        else:
            slippage = 0
        
        if side == "BUY":
            return mid_price * (1 + slippage)
        else:
            return mid_price * (1 - slippage)
    
    def update_positions(self, snapshot):
        """Update position values."""
        for pos in self.positions.values():
            pos["current_price"] = snapshot.get("mid_price", pos.get("entry_price", 0.5))
    
    def position_value(self, snapshot) -> float:
        """Calculate total position value."""
        return sum(
            p["size"] * p.get("current_price", p.get("entry_price", 0.5))
            for p in self.positions.values()
        )
    
    def generate_results(self) -> BacktestResult:
        """Calculate performance metrics."""
        equity = np.array(self.equity_curve)
        returns = np.diff(equity) / equity[:-1]
        
        # Basic metrics
        total_return = (equity[-1] - equity[0]) / equity[0]
        
        # Sharpe ratio (annualized, assuming hourly data)
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 * 24)
        else:
            sharpe = 0
        
        # Max drawdown
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_drawdown = np.max(drawdown)
        
        # Trading metrics
        if self.trades:
            pnl = [t.get("pnl", 0) for t in self.trades]
            wins = [p for p in pnl if p > 0]
            losses = [p for p in pnl if p <= 0]
            
            hit_rate = len(wins) / len(pnl) if pnl else 0
            avg_win = np.mean(wins) if wins else 0
            avg_loss = np.mean(losses) if losses else 0
            
            gross_profit = sum(wins)
            gross_loss = abs(sum(losses))
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
            
            durations = [t.get("duration", 0) for t in self.trades]
            avg_duration = np.mean(durations) if durations else 0
        else:
            hit_rate = avg_win = avg_loss = profit_factor = avg_duration = 0
        
        return BacktestResult(
            total_return=total_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            hit_rate=hit_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            num_trades=len(self.trades),
            avg_trade_duration=avg_duration,
            equity_curve=self.equity_curve,
            drawdown_curve=drawdown.tolist(),
            trade_log=self.trades
        )


class HistoricalData:
    """Historical market data for backtesting."""
    
    def __init__(self, data: List[dict] = None):
        self.data = data or []
        self.index = 0
    
    @classmethod
    def from_api(cls, api_client, market_id: str, **params):
        """Load historical data from API."""
        # Would implement actual API call
        return cls()
    
    @classmethod
    def from_csv(cls, filepath: str):
        """Load historical data from CSV."""
        import pandas as pd
        df = pd.read_csv(filepath)
        data = df.to_dict("records")
        return cls(data)
    
    def stream(self):
        """Iterate over data points."""
        for row in self.data:
            yield row.get("timestamp", 0), row
    
    def __len__(self):
        return len(self.data)
    
    def split(self, train_ratio: float = 0.7):
        """Split into train/test sets."""
        split_idx = int(len(self.data) * train_ratio)
        return (
            HistoricalData(self.data[:split_idx]),
            HistoricalData(self.data[split_idx:])
        )


def walk_forward_backtest(data: HistoricalData, 
                         strategy_factory: Callable,
                         train_window: int = 720,
                         test_window: int = 168,
                         step: int = 24) -> List[BacktestResult]:
    """
    Perform walk-forward backtesting.
    
    Args:
        data: Full historical dataset
        strategy_factory: Function to create strategy with given parameters
        train_window: Size of training window (hours)
        test_window: Size of test window (hours)
        step: Step size between windows (hours)
    """
    results = []
    
    for i in range(0, len(data) - train_window - test_window, step):
        train_data = HistoricalData(list(data.data)[i:i+train_window])
        test_data = HistoricalData(list(data.data)[i+train_window:i+train_window+test_window])
        
        # Create and train strategy on training data
        strategy = strategy_factory(train_data)
        
        # Test on out-of-sample data
        engine = BacktestEngine()
        result = engine.run(test_data, strategy)
        results.append(result)
    
    return results


def plot_equity_curve(result: BacktestResult, output_path: str = None):
    """Generate equity curve plot."""
    import matplotlib.pyplot as plt
    
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Equity curve
    ax1.plot(result.equity_curve)
    ax1.set_title(f"Equity Curve - Return: {result.total_return:.2%}, Sharpe: {result.sharpe_ratio:.2f}")
    ax1.set_ylabel("Portfolio Value")
    ax1.grid(True)
    
    # Drawdown
    ax2.fill_between(range(len(result.drawdown_curve)), result.drawdown_curve)
    ax2.set_title(f"Drawdown - Max: {result.max_drawdown:.2%}")
    ax2.set_ylabel("Drawdown")
    ax2.set_xlabel("Time")
    ax2.grid(True)
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path)
    else:
        plt.show()
