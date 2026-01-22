"""
Risk management system for trading operations.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class RiskEventType(Enum):
    TIME_STOP = "TIME_STOP"
    PROB_DRIFT = "PROB_DRIFT"
    TRAILING_STOP = "TRAILING_STOP"
    DRAWDOWN_LIMIT = "DRAWDOWN_LIMIT"
    CORRELATION_BREACH = "CORRELATION_BREACH"


@dataclass
class RiskEvent:
    type: RiskEventType
    market_id: str
    reason: str
    recommended_action: str  # "CLOSE", "CLOSE_HALF", "REDUCE"
    current_pnl: float = 0
    timestamp: float = 0


@dataclass
class RiskCheckResult:
    approved: bool
    reason: str = ""
    adjusted_size: float = 0
    risk_events: List[RiskEvent] = field(default_factory=list)


class RiskManager:
    """
    Comprehensive risk management for trading operations.
    
    Handles:
    - Position limits
    - Correlation management
    - Stop losses
    - Drawdown limits
    - Kill switch
    """
    
    def __init__(self, config):
        self.config = config
        self.max_exposure_per_market = config.max_exposure_per_market
        self.max_exposure_per_outcome = config.max_exposure_per_outcome
        self.max_correlated_exposure = config.max_correlated_exposure
        self.max_drawdown_limit = config.max_drawdown_limit
        self.kill_switch_threshold = config.kill_switch_threshold
        self.default_stop_loss = config.default_stop_loss
        self.trailing_stop = config.trailing_stop
        
        # Correlation groups
        self.correlation_groups: Dict[str, List[str]] = {}
        
        # Outcome tracking
        self.outcome_exposure: Dict[str, float] = {}
        
        # Daily limits
        self.daily_loss_limit = 0.03  # 3% of capital
    
    def can_open_position(self, market_id: str, side: str, 
                          size: float, portfolio) -> Tuple[bool, str]:
        """
        Check if a new position can be opened.
        
        Returns:
            Tuple of (approved, reason)
        """
        # Check per-market exposure
        current_exposure = self._get_market_exposure(market_id, portfolio)
        new_exposure = current_exposure + size
        
        if new_exposure > self.max_exposure_per_market * portfolio.total_value:
            return False, f"Per-market limit: {new_exposure:.2%} > {self.max_exposure_per_market:.2%}"
        
        # Check outcome concentration
        outcome = self._get_outcome_from_market(market_id, side)
        current_outcome_exposure = self.outcome_exposure.get(outcome, 0)
        new_outcome_exposure = current_outcome_exposure + size
        
        if new_outcome_exposure > self.max_exposure_per_outcome * portfolio.total_value:
            return False, f"Outcome limit: {new_outcome_exposure:.2%} > {self.max_exposure_per_outcome:.2%}"
        
        # Check correlated exposure
        correlated = self._get_correlated_exposure(market_id, portfolio)
        new_correlated = correlated + size
        
        if new_correlated > self.max_correlated_exposure * portfolio.total_value:
            return False, f"Correlated limit: {new_correlated:.2%} > {self.max_correlated_exposure:.2%}"
        
        # Check drawdown
        if portfolio.drawdown > self.max_drawdown_limit:
            return False, f"Drawdown limit active: {portfolio.drawdown:.2%} > {self.max_drawdown_limit:.2%}"
        
        # Check daily loss
        if portfolio.daily_pnl < -self.daily_loss_limit * portfolio.total_value:
            return False, f"Daily loss limit exceeded: {portfolio.daily_pnl:.2%}"
        
        return True, "Approved"
    
    def check_stops(self, position, current_price: float = None) -> List[RiskEvent]:
        """Check all stop conditions for a position."""
        events = []
        
        if current_price is None:
            current_price = position.current_price
        
        # Time stop: 48 hours at loss
        hours_held = (datetime.utcnow().timestamp() - position.entry_time) / 3600
        if hours_held > 48 and position.pnl_pct < 0:
            events.append(RiskEvent(
                type=RiskEventType.TIME_STOP,
                market_id=position.market_id,
                reason=f"Held {hours_held:.1f}hrs at {position.pnl_pct:.1%} P&L",
                recommended_action="CLOSE",
                current_pnl=position.pnl,
                timestamp=datetime.utcnow().timestamp()
            ))
        
        # Probability drift stop
        if hasattr(position, 'entry_probability') and position.entry_probability:
            drift = current_price - position.entry_probability
            
            if position.side.value == "BUY" and drift < -0.15:
                events.append(RiskEvent(
                    type=RiskEventType.PROB_DRIFT,
                    market_id=position.market_id,
                    reason=f"Probability dropped {abs(drift):.1%} since entry",
                    recommended_action="CLOSE_HALF",
                    current_pnl=position.pnl,
                    timestamp=datetime.utcnow().timestamp()
                ))
            elif position.side.value == "SELL" and drift > 0.15:
                events.append(RiskEvent(
                    type=RiskEventType.PROB_DRIFT,
                    market_id=position.market_id,
                    reason=f"Probability rose {drift:.1%} since entry",
                    recommended_action="CLOSE_HALF",
                    current_pnl=position.pnl,
                    timestamp=datetime.utcnow().timestamp()
                ))
        
        # Trailing stop for winning positions
        if position.pnl_pct > 0.20:
            if hasattr(position, 'peak_pnl'):
                if position.pnl_pct < position.peak_pnl * (1 - self.trailing_stop):
                    events.append(RiskEvent(
                        type=RiskEventType.TRAILING_STOP,
                        market_id=position.market_id,
                        reason=f"Pullback from peak {position.peak_pnl:.1%}",
                        recommended_action="CLOSE_ALL",
                        current_pnl=position.pnl,
                        timestamp=datetime.utcnow().timestamp()
                    ))
            else:
                position.peak_pnl = position.pnl_pct
        
        return events
    
    def calculate_position_size(self, market_id: str, edge: float,
                               confidence: float, portfolio) -> float:
        """
        Calculate optimal position size based on edge and risk.
        
        Uses modified Kelly criterion:
        Kelly = p - (1-p)/b
        Where b = payoff ratio
        
        Then applies fractional Kelly (1/4) for safety.
        """
        if edge <= 0:
            return 0
        
        # Assume payoff ratio based on edge
        payoff_ratio = edge / (1 - edge)
        
        # Kelly calculation
        # p = probability of edge being correct (assume proportional to edge)
        p = min(0.95, 0.5 + edge)
        kelly = p - (1 - p) / payoff_ratio if payoff_ratio > 0 else 0
        
        # Fractional Kelly for safety
        fractional_kelly = max(0, kelly * 0.25)
        
        # Scale by confidence
        size = fractional_kelly * confidence
        
        # Scale by available capital
        max_size = self.max_exposure_per_market * portfolio.total_value
        size = min(size, max_size)
        
        return size
    
    def _get_market_exposure(self, market_id: str, portfolio) -> float:
        """Get current exposure for a market."""
        if market_id in portfolio.positions:
            pos = portfolio.positions[market_id]
            return pos.size * pos.current_price
        return 0
    
    def _get_outcome_from_market(self, market_id: str, side: str) -> str:
        """Extract outcome from market ID and side."""
        # Simplified - would need proper market metadata
        return f"{market_id}_{side}"
    
    def _get_correlated_exposure(self, market_id: str, portfolio) -> float:
        """Get total exposure across correlated markets."""
        total = self._get_market_exposure(market_id, portfolio)
        
        for group_name, group_markets in self.correlation_groups.items():
            if market_id in group_markets:
                for m in group_markets:
                    if m != market_id:
                        total += self._get_market_exposure(m, portfolio)
                break
        
        return total
    
    def set_correlation_group(self, group_name: str, markets: List[str]):
        """Set correlation group for related markets."""
        self.correlation_groups[group_name] = markets
    
    def get_risk_summary(self, portfolio) -> Dict:
        """Get comprehensive risk summary."""
        return {
            "total_exposure": sum(
                p.size * p.current_price for p in portfolio.positions.values()
            ),
            "per_market_exposures": {
                m: p.size * p.current_price
                for m, p in portfolio.positions.items()
            },
            "outcome_exposures": self.outcome_exposure,
            "current_drawdown": portfolio.drawdown,
            "daily_pnl": portfolio.daily_pnl,
            "num_positions": len(portfolio.positions),
            "kill_switch_triggered": portfolio.drawdown > self.kill_switch_threshold
        }
