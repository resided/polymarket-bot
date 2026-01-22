"""
External reference mispricing detection engine.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple
from statistics import mean, stdev
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class MispricingSignal:
    strategy_type: str = "MISPRICING"
    market_id: str = ""
    side: str = ""  # "BUY_POLY" or "SELL_POLY"
    size: float = 0
    limit_price: float = 0
    confidence: float = 0
    edge: float = 0
    z_score: float = 0
    source_agreement: float = 0
    timestamp: float = 0


class ExternalMispricingEngine:
    """
    Detect mispricing by comparing Polymarket prices to external reference probabilities.
    
    Supports:
    - Election forecast models (FiveThirtyEight, Economist)
    - Sportsbooks and betting exchanges
    - Other prediction markets (Kalshi, Manifold)
    - Custom models
    """
    
    def __init__(self, decay_half_life: float = 3600):
        self.decay_half_life = decay_half_life
        self.external_signals: Dict[str, Dict] = {}
        self.source_weights: Dict[str, float] = {}
        self.source_mae: Dict[str, Dict[str, float]] = {}  # source -> market -> MAE
        self.price_history: Dict[str, deque] = {}
        
        # Thresholds
        self.min_z_score = 2.0
        self.min_confidence = 0.5
        self.min_source_agreement = 0.6
        
        # Learning rate for source weights
        self.learning_rate = 0.01
    
    def generate_signal(self, market_id: str, poly_price: float) -> Optional[MispricingSignal]:
        """Generate trading signal based on external reference comparison."""
        fair_prob, deviation, confidence = self.calculate_fair_probability(
            market_id, poly_price
        )
        
        if fair_prob == poly_price:
            return None
        
        # Calculate z-score
        typical_deviation = 0.05  # 5% typical deviation
        z_score = deviation / typical_deviation
        
        # Check if deviation is significant
        if abs(z_score) < self.min_z_score:
            return None
        
        if confidence < self.min_confidence:
            return None
        
        # Check source agreement
        source_agreement = self._calculate_source_agreement(market_id, deviation)
        if source_agreement < self.min_source_agreement:
            return None
        
        # Determine trade direction
        if poly_price > fair_prob:
            # Polymarket overpriced - sell
            signal = MispricingSignal(
                market_id=market_id,
                side="SELL",
                size=self._calculate_size(deviation, confidence),
                limit_price=poly_price - 0.002,  # Passive execution
                confidence=confidence,
                edge=deviation,
                z_score=z_score,
                source_agreement=source_agreement,
                timestamp=time.time()
            )
        else:
            # Polymarket underpriced - buy
            signal = MispricingSignal(
                market_id=market_id,
                side="BUY",
                size=self._calculate_size(abs(deviation), confidence),
                limit_price=poly_price + 0.002,
                confidence=confidence,
                edge=abs(deviation),
                z_score=abs(z_score),
                source_agreement=source_agreement,
                timestamp=time.time()
            )
        
        return signal
    
    def calculate_fair_probability(self, market_id: str, 
                                   poly_price: float) -> Tuple[float, float, float]:
        """
        Calculate fair probability using weighted external sources.
        
        Uses Bayesian update: posterior = weighted average of observations
        weighted by inverse variance (confidence).
        """
        signals = self.external_signals.get(market_id, {})
        if not signals:
            return poly_price, 0.0, 0.0
        
        now = time.time()
        weighted_sum = 0.0
        weight_sum = 0.0
        source_deviations = []
        
        for source, data in signals.items():
            age = now - data["timestamp"]
            decay = 0.5 ** (age / self.decay_half_life)
            
            # Weight by source accuracy and freshness
            source_weight = self.source_weights.get(source, 0.5)
            weight = source_weight * decay
            
            weighted_sum += data["probability"] * weight
            weight_sum += weight
            
            source_deviations.append(data["probability"] - poly_price)
        
        if weight_sum < 0.1:
            return poly_price, 0.0, 0.0
        
        composite_prob = weighted_sum / weight_sum
        deviation = poly_price - composite_prob
        
        # Confidence based on agreement and freshness
        if len(source_deviations) > 1:
            # High agreement = high confidence
            agreement = 1 - stdev(source_deviations) if len(source_deviations) > 1 else 1
            confidence = min(1.0, weight_sum * agreement)
        else:
            confidence = min(1.0, weight_sum)
        
        return composite_prob, deviation, confidence
    
    def _calculate_source_agreement(self, market_id: str, 
                                   deviation: float) -> float:
        """Calculate what fraction of sources agree on the deviation direction."""
        signals = self.external_signals.get(market_id, {})
        if not signals:
            return 0.0
        
        agreeing = sum(
            1 for data in signals.values()
            if (data["probability"] - 0.5) * (deviation) > 0
        )
        
        return agreeing / len(signals) if signals else 0.0
    
    def _calculate_size(self, deviation: float, confidence: float) -> float:
        """
        Calculate position size based on deviation and confidence.
        
        Uses modified Kelly criterion with fractional Kelly.
        """
        # Assume payoff ratio based on deviation
        payoff_ratio = deviation / (1 - deviation) if deviation < 0.5 else deviation
        
        # Kelly fraction
        kelly = deviation * payoff_ratio - (1 - deviation)
        
        # Use 1/4 Kelly for safety
        fractional_kelly = max(0, kelly * 0.25)
        
        # Scale by confidence
        size = fractional_kelly * confidence
        
        # Cap at 3% of capital per trade
        return min(size, 0.03)
    
    def update_external_signal(self, market_id: str, source: str,
                              probability: float, timestamp: float):
        """Update external signal for a market."""
        if market_id not in self.external_signals:
            self.external_signals[market_id] = {}
        
        self.external_signals[market_id][source] = {
            "probability": probability,
            "timestamp": timestamp
        }
        
        # Update source weight based on historical accuracy
        self._update_source_weight(source, market_id, probability)
    
    def _update_source_weight(self, source: str, market_id: str,
                             current_estimate: float):
        """Update source weight based on historical accuracy."""
        if source not in self.source_mae:
            self.source_mae[source] = {}
        
        # Would need resolution data to calculate actual MAE
        # This is a placeholder for the learning mechanism
        self.source_mae[source][market_id] = self.source_mae[source].get(market_id, 0.05)
        
        # Higher weight for sources with lower historical MAE
        self.source_weights[source] = 1.0 / (1.0 + self.source_mae[source].get(market_id, 0.05) * 100)
    
    def record_resolution(self, market_id: str, actual_outcome: float):
        """Record market resolution to update source accuracy metrics."""
        if market_id not in self.external_signals:
            return
        
        for source, data in self.external_signals[market_id].items():
            estimate = data["probability"]
            error = abs(estimate - actual_outcome)
            
            if source not in self.source_mae:
                self.source_mae[source] = {}
            
            # Exponential moving average of MAE
            prev_mae = self.source_mae[source].get(market_id, 0.05)
            new_mae = prev_mae * (1 - self.learning_rate) + error * self.learning_rate
            self.source_mae[source][market_id] = new_mae
            
            # Update weight
            self.source_weights[source] = 1.0 / (1.0 + new_mae * 100)
        
        # Clean up resolved market
        del self.external_signals[market_id]
    
    def get_composite_signal(self, market_id: str) -> Dict:
        """Get summary of external signals for a market."""
        signals = self.external_signals.get(market_id, {})
        return {
            "num_sources": len(signals),
            "avg_probability": mean(d["probability"] for d in signals.values()) if signals else None,
            "sources": {
                s: {
                    "probability": d["probability"],
                    "age_seconds": time.time() - d["timestamp"]
                }
                for s, d in signals.items()
            }
        }
