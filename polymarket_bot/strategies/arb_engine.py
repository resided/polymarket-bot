"""
Arbitrage detection engine for cross-market opportunities.
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime

from ..core.state import OrderBook, OrderSide

logger = logging.getLogger(__name__)


@dataclass
class ArbOpportunity:
    type: str  # COMPLEMENTARY, TRIANGULAR, TEMPORAL
    buy_market: str
    sell_market: str
    buy_price: float
    sell_price: float
    edge: float
    max_size: float
    timestamp: float = 0
    confidence: float = 1.0


class ArbDetector:
    """Detect arbitrage opportunities across Polymarket markets."""
    
    def __init__(self, fee_rate: float = 0.001):
        self.fee_rate = fee_rate
        self.min_edge = 0.003  # 30 bps minimum edge
        self.min_liquidity = 100  # Minimum dollar liquidity
    
    def check(self, book_a: OrderBook, book_b: OrderBook) -> Optional[ArbOpportunity]:
        """Check for arbitrage between two order books."""
        if not book_a or not book_b:
            return None
        
        # Check complementary (binary) relationship
        if opp := self._check_complementary(book_a, book_b):
            return opp
        
        # Check triangular relationships
        if opp := self._check_triangular(book_a, book_b):
            return opp
        
        return None
    
    def _check_complementary(self, book_a: OrderBook, 
                            book_b: OrderBook) -> Optional[ArbOpportunity]:
        """Check for arbitrage in complementary binary outcomes."""
        price_a = book_a.mid_price
        price_b = book_b.mid_price
        sum_prob = price_a + price_b
        
        # Account for fees (both sides pay fees)
        total_fee = 2 * self.fee_rate
        upper_bound = 1 + total_fee
        lower_bound = 1 - total_fee
        
        # Check if prices violate no-arbitrage bounds
        if sum_prob > upper_bound:
            # Sell the overpriced outcome, buy the underpriced
            if price_a > price_b:
                edge = (sum_prob - upper_bound) / sum_prob
                return ArbOpportunity(
                    type="COMPLEMENTARY",
                    buy_market=book_b.market_id,
                    sell_market=book_a.market_id,
                    buy_price=book_b.best_bid,  # Buy at bid
                    sell_price=book_a.best_ask,  # Sell at ask
                    edge=edge,
                    max_size=self._calculate_max_size(book_a, book_b),
                    timestamp=datetime.utcnow().timestamp()
                )
            else:
                edge = (sum_prob - upper_bound) / sum_prob
                return ArbOpportunity(
                    type="COMPLEMENTARY",
                    buy_market=book_a.market_id,
                    sell_market=book_b.market_id,
                    buy_price=book_a.best_bid,
                    sell_price=book_b.best_ask,
                    edge=edge,
                    max_size=self._calculate_max_size(book_a, book_b),
                    timestamp=datetime.utcnow().timestamp()
                )
        
        elif sum_prob < lower_bound:
            # Prices are too low - buy both
            if price_a < price_b:
                edge = (lower_bound - sum_prob) / sum_prob
                return ArbOpportunity(
                    type="COMPLEMENTARY",
                    buy_market=book_a.market_id,
                    sell_market=book_b.market_id,
                    buy_price=book_a.best_ask,
                    sell_price=book_b.best_bid,
                    edge=edge,
                    max_size=self._calculate_max_size(book_a, book_b),
                    timestamp=datetime.utcnow().timestamp()
                )
            else:
                edge = (lower_bound - sum_prob) / sum_prob
                return ArbOpportunity(
                    type="COMPLEMENTARY",
                    buy_market=book_b.market_id,
                    sell_market=book_a.market_id,
                    buy_price=book_b.best_ask,
                    sell_price=book_a.best_bid,
                    edge=edge,
                    max_size=self._calculate_max_size(book_a, book_b),
                    timestamp=datetime.utcnow().timestamp()
                )
        
        return None
    
    def _check_triangular(self, book_a: OrderBook,
                         book_b: OrderBook) -> Optional[ArbOpportunity]:
        """
        Check for triangular arbitrage.
        
        Example: Fed rates market -> Rate cut amount market -> Timing market
        Implied probabilities must satisfy transitive constraints.
        """
        # This is a simplified version - full implementation would handle
        # arbitrary logical relationships
        
        price_a = book_a.mid_price
        price_b = book_b.mid_price
        
        # Example: If P(A) > P(A|B) * P(B), there may be arbitrage
        # This requires knowing the conditional relationship
        
        # For now, return None - would need market-specific logic
        return None
    
    def _calculate_max_size(self, book_a: OrderBook, 
                           book_b: OrderBook) -> float:
        """Calculate maximum position size based on liquidity."""
        # Consider both sides of the trade
        buy_depth = min(
            book_a.bid_depth if hasattr(book_a, 'bid_depth') else 0,
            book_b.ask_depth if hasattr(book_b, 'ask_depth') else 0
        )
        
        sell_depth = min(
            book_a.ask_depth if hasattr(book_a, 'ask_depth') else 0,
            book_b.bid_depth if hasattr(book_b, 'bid_depth') else 0
        )
        
        # Use the limiting side, with 50% safety margin
        max_size = min(buy_depth, sell_depth) * 0.5
        
        return max(0, min(max_size, 10000))  # Cap at $10k per trade
    
    def check_multi_leg(self, markets: List[OrderBook], 
                       constraints: List[Dict]) -> Optional[ArbOpportunity]:
        """
        Check for arbitrage in multi-leg structures.
        
        Example: 
        - Market 1: "A wins" at $0.60
        - Market 2: "B wins" at $0.30
        - Market 3: "A or B wins" at $0.95
        
        Constraint: P(A) + P(B) = P(A or B)
        0.60 + 0.30 = 0.90 < 0.95 → Buy A+B, sell AorB
        """
        if len(markets) < 3:
            return None
        
        # Sum of individual probabilities
        individual_sum = sum(m.total_probability for m in markets[:-1])
        
        # Probability of union (last market)
        union_prob = markets[-1].mid_price
        
        # Check constraint violation
        if individual_sum > union_prob + 2 * self.fee_rate:
            # Buy union, sell individuals
            pass
        elif individual_sum < union_prob - 2 * self.fee_rate:
            # Buy individuals, sell union
            pass
        
        return None
    
    def calculate_edge(self, buy_price: float, sell_price: float,
                      fees: float = 0) -> float:
        """Calculate raw edge after fees."""
        gross_edge = sell_price - buy_price
        net_edge = gross_edge - fees
        return net_edge / buy_price
    
    def is_profitable(self, opportunity: ArbOpportunity) -> bool:
        """Check if arbitrage opportunity is worth pursuing."""
        if opportunity.edge < self.min_edge:
            return False
        
        if opportunity.max_size < self.min_liquidity:
            return False
        
        return True
