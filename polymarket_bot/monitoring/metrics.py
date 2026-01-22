"""
Monitoring and metrics collection.
"""

import time
from dataclasses import dataclass
from typing import Dict, List
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class MetricsCollector:
    """Collect and expose trading metrics."""
    
    def __init__(self):
        # Counters
        self.trades_total = Counter(
            'polymarket_trades_total',
            'Total number of trades',
            ['strategy', 'status']
        )
        
        self.rejected_trades = Counter(
            'polymarket_rejected_trades_total',
            'Total rejected trades',
            ['strategy', 'reason']
        )
        
        self.order_fills = Counter(
            'polymarket_order_fills_total',
            'Total order fills',
            ['market_id']
        )
        
        # Gauges
        self.portfolio_value = Gauge(
            'polymarket_portfolio_value',
            'Current portfolio value'
        )
        
        self.open_positions = Gauge(
            'polymarket_open_positions',
            'Number of open positions'
        )
        
        self.cash_balance = Gauge(
            'polymarket_cash_balance',
            'Cash balance'
        )
        
        self.drawdown = Gauge(
            'polymarket_drawdown',
            'Current drawdown'
        )
        
        # Histograms
        self.order_latency = Histogram(
            'polymarket_order_latency_seconds',
            'Order placement latency',
            ['strategy'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
        )
        
        self.trade_pnl = Histogram(
            'polymarket_trade_pnl',
            'Trade P&L distribution',
            buckets=[-0.2, -0.1, -0.05, -0.02, 0, 0.02, 0.05, 0.1, 0.2]
        )
        
        self.spread_capture = Histogram(
            'polymarket_spread_capture',
            'Spread capture in bps',
            buckets=[0, 5, 10, 25, 50, 100, 250]
        )
        
        # Strategy-specific metrics
        self.arb_opportunities = Counter(
            'polymarket_arb_opportunities_total',
            'Total arbitrage opportunities detected',
            ['type']
        )
        
        self.mispricing_signals = Counter(
            'polymarket_mispricing_signals_total',
            'Total mispricing signals',
            ['direction']
        )
        
        self.micro_signals = Counter(
            'polymarket_micro_signals_total',
            'Total microstructure signals',
            ['direction']
        )
    
    def record_trade(self, strategy: str, status: str):
        """Record a trade attempt."""
        self.trades_total.labels(strategy=strategy, status=status).inc()
    
    def record_rejected(self, strategy: str, reason: str = "risk"):
        """Record a rejected trade."""
        self.rejected_trades.labels(strategy=strategy, reason=reason).inc()
    
    def record_fill(self, fill):
        """Record order fill."""
        self.order_fills.labels(market_id=fill.market_id).inc()
    
    def record_order_latency(self, strategy: str, latency: float):
        """Record order placement latency."""
        self.order_latency.labels(strategy=strategy).observe(latency)
    
    def record_pnl(self, pnl_pct: float):
        """Record trade P&L."""
        self.trade_pnl.observe(pnl_pct)
    
    def record_spread_capture(self, bps: float):
        """Record spread capture in basis points."""
        self.spread_capture.observe(bps)
    
    def update_portfolio(self, portfolio):
        """Update portfolio metrics."""
        self.portfolio_value.set(portfolio.total_value)
        self.open_positions.set(len(portfolio.positions))
        self.cash_balance.set(portfolio.cash)
        self.drawdown.set(portfolio.drawdown)
    
    def record_arb_opportunity(self, arb_type: str):
        """Record detected arbitrage opportunity."""
        self.arb_opportunities.labels(type=arb_type).inc()
    
    def record_mispricing_signal(self, direction: str):
        """Record mispricing signal."""
        self.mispricing_signals.labels(direction=direction).inc()
    
    def record_micro_signal(self, direction: str):
        """Record microstructure signal."""
        self.micro_signals.labels(direction=direction).inc()


@dataclass
class HealthStatus:
    name: str
    healthy: bool
    last_check: float
    details: str = ""


class HealthCheck:
    """Health check endpoint manager."""
    
    def __init__(self):
        self.checks: Dict[str, HealthStatus] = {}
        self._unhealthy = False
        self._unhealthy_reason = ""
    
    def register_check(self, name: str, check_fn):
        """Register a health check function."""
        self.checks[name] = {
            "fn": check_fn,
            "status": HealthStatus(name, True, time.time())
        }
    
    async def run_checks(self) -> Dict[str, HealthStatus]:
        """Run all health checks."""
        results = {}
        
        for name, check in self.checks.items():
            try:
                healthy = await check["fn"]()
                results[name] = HealthStatus(
                    name=name,
                    healthy=healthy,
                    last_check=time.time()
                )
            except Exception as e:
                results[name] = HealthStatus(
                    name=name,
                    healthy=False,
                    last_check=time.time(),
                    details=str(e)
                )
        
        return results
    
    def set_unhealthy(self, reason: str):
        """Set kill switch as unhealthy."""
        self._unhealthy = True
        self._unhealthy_reason = reason
    
    def is_healthy(self) -> bool:
        """Check overall health."""
        if self._unhealthy:
            return False
        
        for check in self.checks.values():
            if not check["status"].healthy:
                return False
        
        return True
    
    def get_status(self) -> Dict:
        """Get full health status."""
        return {
            "healthy": self.is_healthy(),
            "kill_switch_triggered": self._unhealthy,
            "kill_switch_reason": self._unhealthy_reason,
            "checks": {
                name: {
                    "healthy": status.healthy,
                    "last_check": status.last_check,
                    "details": status.details
                }
                for name, status in self.checks.items()
            }
        }


def start_metrics_server(port: int = 9090):
    """Start Prometheus metrics server."""
    start_http_server(port)
    logger.info(f"Metrics server started on port {port}")
