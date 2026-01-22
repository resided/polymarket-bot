"""
Thread-safe shared state management.
"""

import asyncio
import threading
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque
from dataclasses import dataclass
from enum import Enum
from datetime import datetime


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class OrderBookLevel:
    price: float
    size: float
    order_id: str


@dataclass
class OrderBook:
    market_id: str
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    mid_price: float = 0.5
    last_update: float = 0
    sequence: int = 0
    
    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None
    
    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None
    
    @property
    def spread(self) -> float:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return 0
    
    @property
    def spread_bps(self) -> float:
        return (self.spread / self.mid_price) * 10000 if self.mid_price > 0 else 0
    
    @property
    def bid_depth(self) -> float:
        return sum(b.size for b in self.bids[:5])
    
    @property
    def ask_depth(self) -> float:
        return sum(a.size for a in self.asks[:5])


@dataclass
class Position:
    market_id: str
    side: OrderSide
    size: float
    entry_price: float
    entry_time: float
    current_price: float = 0
    stop_loss: float = None
    take_profit: float = None
    
    @property
    def pnl(self) -> float:
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * self.size
        else:
            return (self.entry_price - self.current_price) * self.size
    
    @property
    def pnl_pct(self) -> float:
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) / self.entry_price
        else:
            return (self.entry_price - self.current_price) / self.entry_price


@dataclass
class Order:
    order_id: str
    market_id: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float]
    status: str = "PENDING"
    filled_size: float = 0
    fill_price: Optional[float] = None
    timestamp: float = 0
    nonce: str = ""


@dataclass
class Trade:
    trade_id: str
    market_id: str
    side: OrderSide
    size: float
    price: float
    timestamp: float
    fees: float = 0
    pnl: float = 0


@dataclass
class Portfolio:
    cash: float = 100000
    positions: Dict[str, Position] = field(default_factory=dict)
    trades: List[Trade] = field(default_factory=list)
    starting_capital: float = 100000
    
    @property
    def total_value(self) -> float:
        position_value = sum(
            p.size * p.current_price for p in self.positions.values()
        )
        return self.cash + position_value
    
    @property
    def daily_pnl(self) -> float:
        today = datetime.now().date()
        today_trades = [t for t in self.trades 
                       if datetime.fromtimestamp(t.timestamp).date() == today]
        return sum(t.pnl for t in today_trades)
    
    @property
    def drawdown(self) -> float:
        peak = self.starting_capital
        current = self.total_value
        return (peak - current) / peak if peak > current else 0


class SharedState:
    """Thread-safe shared state for the trading bot."""
    
    def __init__(self, initial_capital: float = 100000):
        self._lock = threading.Lock()
        self._order_books: Dict[str, OrderBook] = {}
        self._portfolio = Portfolio(cash=initial_capital, 
                                   starting_capital=initial_capital)
        self._pending_orders: Dict[str, Order] = {}
        self._trades: List[Trade] = []
        self._related_markets: Dict[str, List[str]] = {}
        self._external_signals: Dict[str, Dict] = {}
        self._price_history: Dict[str, Deque] = {}
        self._order_flow: Dict[str, Deque] = {}
    
    # Order Book methods
    def update_book(self, market_id: str, bids: List, asks: List, 
                   sequence: int, timestamp: float):
        with self._lock:
            if market_id not in self._order_books:
                self._order_books[market_id] = OrderBook(market_id=market_id)
            
            book = self._order_books[market_id]
            book.bids = [OrderBookLevel(*b) for b in bids]
            book.asks = [OrderBookLevel(*a) for a in asks]
            book.mid_price = (book.best_bid + book.best_ask) / 2 if book.best_bid and book.best_ask else 0.5
            book.sequence = sequence
            book.last_update = timestamp
            
            # Update price history
            if market_id not in self._price_history:
                self._price_history[market_id] = deque(maxlen=1000)
            self._price_history[market_id].append({
                "price": book.mid_price,
                "timestamp": timestamp
            })
    
    def get_book(self, market_id: str) -> Optional[OrderBook]:
        with self._lock:
            return copy.deepcopy(self._order_books.get(market_id))
    
    def get_all_books(self) -> Dict[str, OrderBook]:
        with self._lock:
            return copy.deepcopy(self._order_books)
    
    # Portfolio methods
    def update_position(self, trade: Trade):
        with self._lock:
            position_key = f"{trade.market_id}_{trade.side.value}"
            
            if trade.market_id in self._portfolio.positions:
                pos = self._portfolio.positions[trade.market_id]
                # Average in
                new_size = pos.size + trade.size
                avg_price = (pos.entry_price * pos.size + trade.price * trade.size) / new_size
                pos.size = new_size
                pos.entry_price = avg_price
                pos.current_price = trade.price
            else:
                self._portfolio.positions[trade.market_id] = Position(
                    market_id=trade.market_id,
                    side=trade.side,
                    size=trade.size,
                    entry_price=trade.price,
                    entry_time=trade.timestamp,
                    current_price=trade.price
                )
            
            # Update cash
            if trade.side == OrderSide.BUY:
                self._portfolio.cash -= trade.size * trade.price + trade.fees
            else:
                self._portfolio.cash += trade.size * trade.price - trade.fees
            
            self._portfolio.trades.append(trade)
    
    def close_position(self, market_id: str, close_price: float, 
                      timestamp: float) -> Optional[Trade]:
        with self._lock:
            if market_id not in self._portfolio.positions:
                return None
            
            pos = self._portfolio.positions[market_id]
            trade = Trade(
                trade_id=f"close_{timestamp}",
                market_id=market_id,
                side=OrderSide.SELL if pos.side == OrderSide.BUY else OrderSide.BUY,
                size=pos.size,
                price=close_price,
                timestamp=timestamp,
                pnl=pos.pnl
            )
            
            # Update cash
            if trade.side == OrderSide.BUY:
                self._portfolio.cash -= trade.size * trade.price
            else:
                self._portfolio.cash += trade.size * trade.price
            
            del self._portfolio.positions[market_id]
            self._portfolio.trades.append(trade)
            
            return trade
    
    def get_portfolio(self) -> Portfolio:
        with self._lock:
            return copy.deepcopy(self._portfolio)
    
    def get_positions(self) -> Dict[str, Position]:
        with self._lock:
            return copy.deepcopy(self._portfolio.positions)
    
    # Order management
    def add_pending_order(self, order: Order):
        with self._lock:
            self._pending_orders[order.order_id] = order
    
    def update_order_status(self, order_id: str, status: str, 
                           filled_size: float = 0, fill_price: float = None):
        with self._lock:
            if order_id in self._pending_orders:
                order = self._pending_orders[order_id]
                order.status = status
                order.filled_size = filled_size
                order.fill_price = fill_price
                if status == "FILLED":
                    del self._pending_orders[order_id]
    
    def get_pending_orders(self) -> Dict[str, Order]:
        with self._lock:
            return copy.deepcopy(self._pending_orders)
    
    # Related markets
    def set_related_markets(self, market_id: str, related: List[str]):
        with self._lock:
            self._related_markets[market_id] = related
    
    def get_related_markets(self, market_id: str) -> List[str]:
        with self._lock:
            return self._related_markets.get(market_id, [])
    
    # External signals
    def update_external_signal(self, market_id: str, source: str, 
                              probability: float, timestamp: float):
        with self._lock:
            if market_id not in self._external_signals:
                self._external_signals[market_id] = {}
            self._external_signals[market_id][source] = {
                "probability": probability,
                "timestamp": timestamp
            }
    
    def get_external_signals(self, market_id: str) -> Dict:
        with self._lock:
            return copy.deepcopy(self._external_signals.get(market_id, {}))
    
    # Order flow tracking
    def record_order_flow(self, market_id: str, side: str, size: float):
        with self._lock:
            if market_id not in self._order_flow:
                self._order_flow[market_id] = deque(maxlen=100)
            self._order_flow[market_id].append({
                "side": side,
                "size": size,
                "timestamp": asyncio.get_event_loop().time()
            })
    
    def get_order_flow(self, market_id: str) -> List:
        with self._lock:
            return list(self._order_flow.get(market_id, []))
    
    # Snapshot for backup/recovery
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "portfolio": {
                    "cash": self._portfolio.cash,
                    "positions": {
                        k: {
                            "market_id": v.market_id,
                            "side": v.side.value,
                            "size": v.size,
                            "entry_price": v.entry_price,
                            "entry_time": v.entry_time
                        }
                        for k, v in self._portfolio.positions.items()
                    }
                },
                "pending_orders": len(self._pending_orders)
            }
