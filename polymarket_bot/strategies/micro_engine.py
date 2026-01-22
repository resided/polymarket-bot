"""
Order book microstructure analysis and trading signals.
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MicroSignal:
    strategy_type: str = "MICRO"
    market_id: str = ""
    side: str = ""
    size: float = 0
    limit_price: float = 0
    confidence: float = 0
    imbalance: float = 0
    momentum: float = 0
    timestamp: float = 0


class MicrostructureEngine:
    """
    Analyze order book microstructure for short-term trading signals.
    
    Key signals:
    - Bid-ask depth imbalance
    - Order flow toxicity
    - Price momentum
    - Support/resistance from large orders
    - Trade flow clustering
    """
    
    def __init__(self):
        self.price_history: Dict[str, deque] = {}
        self.order_flow: Dict[str, deque] = {}
        self.trade_log: Dict[str, List] = {}
        
        # Thresholds
        self.imbalance_threshold = 0.3
        self.momentum_threshold = 0.001
        self.min_liquidity = 100  # Minimum depth for signal
        
        # Weights for composite signal
        self.weights = {
            "imbalance": 0.40,
            "order_flow": 0.35,
            "momentum": 0.25
        }
    
    def generate_signal(self, book) -> Optional[MicroSignal]:
        """Generate microstructure-based trading signal."""
        market_id = book.market_id
        
        # Compute signals
        imbalance = self.compute_imbalance(book)
        order_flow = self.compute_order_flow_imbalance(market_id)
        momentum = self.compute_price_momentum(market_id)
        
        # Composite signal
        composite = (
            self.weights["imbalance"] * imbalance +
            self.weights["order_flow"] * order_flow +
            self.weights["momentum"] * momentum * 100  # Scale momentum
        )
        
        # Check liquidity
        if book.bid_depth + book.ask_depth < self.min_liquidity:
            return None
        
        # Generate signal based on composite
        if composite > self.imbalance_threshold:
            return MicroSignal(
                market_id=market_id,
                side="BUY",
                size=self._calculate_size(composite, book),
                limit_price=book.best_ask - 0.001,
                confidence=min(1.0, abs(composite)),
                imbalance=imbalance,
                momentum=momentum,
                timestamp=datetime.utcnow().timestamp()
            )
        elif composite < -self.imbalance_threshold:
            return MicroSignal(
                market_id=market_id,
                side="SELL",
                size=self._calculate_size(abs(composite), book),
                limit_price=book.best_bid + 0.001,
                confidence=min(1.0, abs(composite)),
                imbalance=imbalance,
                momentum=momentum,
                timestamp=datetime.utcnow().timestamp()
            )
        
        return None
    
    def compute_imbalance(self, book) -> float:
        """
        Calculate bid-ask depth imbalance.
        
        Formula: (bid_depth - ask_depth) / (bid_depth + ask_depth)
        
        Values:
        - Positive: More buying pressure
        - Negative: More selling pressure
        - Near 0: Balanced
        """
        bid_depth = book.bid_depth
        ask_depth = book.ask_depth
        total = bid_depth + ask_depth
        
        if total < self.min_liquidity:
            return 0.0
        
        return (bid_depth - ask_depth) / total
    
    def compute_order_flow_imbalance(self, market_id: str, 
                                     window: int = 50) -> float:
        """
        Calculate order flow imbalance from recent trades.
        
        Weights recent trades more heavily.
        """
        flows = self.order_flow.get(market_id, [])[-window:]
        if not flows:
            return 0.0
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for i, flow in enumerate(flows):
            # Linear decay: more recent = higher weight
            weight = (i + 1) / window
            sign = 1 if flow["side"] == "BUY" else -1
            weighted_sum += flow["size"] * sign * weight
            total_weight += weight
        
        return weighted_sum / total_weight if total_weight > 0 else 0.0
    
    def compute_price_momentum(self, market_id: str, 
                               window: int = 20) -> float:
        """
        Calculate short-term price momentum.
        
        Uses exponentially weighted returns.
        """
        history = self.price_history.get(market_id, [])
        if len(history) < window:
            return 0.0
        
        prices = [h["price"] for h in list(history)[-window:]]
        returns = [(prices[i] - prices[i-1]) / prices[i-1] 
                  for i in range(1, len(prices))]
        
        if not returns:
            return 0.0
        
        # Exponential weights
        weights = [0.5 ** (window - i) for i in range(len(returns))]
        weight_sum = sum(weights)
        
        momentum = sum(r * w for r, w in zip(returns, weights)) / weight_sum
        
        return momentum
    
    def detect_support_resistance(self, book) -> Dict[str, float]:
        """
        Detect support and resistance levels from order book.
        
        Returns:
        - support: Highest bid with significant size
        - resistance: Lowest ask with significant size
        """
        support = 0.0
        resistance = 0.0
        significant_size = 1000  # $1000 minimum for "significant"
        
        for bid in book.bids:
            if bid.size >= significant_size and bid.price > support:
                support = bid.price
        
        for ask in book.asks:
            if ask.size >= significant_size and (resistance == 0 or ask.price < resistance):
                resistance = ask.price
        
        return {
            "support": support,
            "resistance": resistance,
            "distance_to_support": book.mid_price - support if support else None,
            "distance_to_resistance": resistance - book.mid_price if resistance else None
        }
    
    def estimate_slippage(self, book, side: str, size: float) -> float:
        """
        Estimate slippage for a given trade size.
        
        Simulates walking the order book.
        """
        levels = book.asks if side == "BUY" else list(reversed(book.bids))
        
        remaining = size
        total_cost = 0.0
        current_price = book.mid_price
        
        for level in levels:
            if remaining <= 0:
                break
            trade_size = min(remaining, level.size)
            total_cost += trade_size * level.price
            remaining -= trade_size
            current_price = level.price
        
        if size == 0:
            return 0.0
        
        avg_price = total_cost / size
        expected_price = book.mid_price
        
        if side == "BUY":
            return (avg_price - expected_price) / expected_price
        else:
            return (expected_price - avg_price) / expected_price
    
    def _calculate_size(self, signal_strength: float, book) -> float:
        """
        Calculate position size based on signal strength.
        
        Base size 1% of capital, scaled by signal confidence.
        """
        base_size = 0.01  # 1% base
        liquidity_factor = min(1.0, (book.bid_depth + book.ask_depth) / 1000)
        
        size = base_size * signal_strength * liquidity_factor
        
        return min(size, 0.02)  # Cap at 2% per trade
    
    def update_price_history(self, market_id: str, price: float, 
                            timestamp: float):
        """Update price history for momentum calculation."""
        if market_id not in self.price_history:
            self.price_history[market_id] = deque(maxlen=1000)
        
        self.price_history[market_id].append({
            "price": price,
            "timestamp": timestamp
        })
    
    def record_trade(self, market_id: str, side: str, size: float):
        """Record a trade for order flow analysis."""
        if market_id not in self.order_flow:
            self.order_flow[market_id] = deque(maxlen=500)
        
        self.order_flow[market_id].append({
            "side": side,
            "size": size,
            "timestamp": datetime.utcnow().timestamp()
        })
    
    def get_book_snapshot(self, market_id: str) -> Dict:
        """Get snapshot of order book state."""
        history = list(self.price_history.get(market_id, []))
        flow = list(self.order_flow.get(market_id, []))
        
        return {
            "price_history_length": len(history),
            "order_flow_length": len(flow),
            "recent_trades": len([f for f in flow if f["timestamp"] > datetime.utcnow().timestamp() - 300]),
            "last_update": history[-1] if history else None
        }
