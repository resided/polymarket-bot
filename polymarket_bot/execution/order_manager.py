"""
Order execution manager for Polymarket.
"""

import asyncio
import logging
import uuid
import time
from dataclasses import dataclass
from typing import Dict, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class OrderRequest:
    market_id: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    nonce: str = ""
    time_in_force: str = "GTC"  # GTC, FOK, IOC


@dataclass
class Order:
    order_id: str
    market_id: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float]
    status: OrderStatus
    filled_size: float = 0
    fill_price: Optional[float] = None
    fees: float = 0
    timestamp: float = 0
    nonce: str = ""
    last_update: float = 0


@dataclass
class Fill:
    fill_id: str
    order_id: str
    market_id: str
    side: OrderSide
    size: float
    price: float
    fees: float
    timestamp: float


class APIError(Exception):
    def __init__(self, message: str, code: int = 500, retryable: bool = False):
        self.message = message
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class OrderManager:
    """
    Handle order placement, cancellation, and fill tracking.
    """
    
    def __init__(self, config, paper_trading: bool = False):
        self.config = config
        self.paper_trading = paper_trading
        self.session = None
        self.pending_orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self.fills: List[Fill] = []
        
        # Rate limiting
        self.orders_per_minute = 30
        self.orders_per_hour = 300
        self.order_timestamps: List[float] = []
        
        # Retry settings
        self.max_retries = 3
        self.base_delay = 0.1
    
    async def get_session(self):
        """Get or create aiohttp session."""
        if self.session is None or self.session.closed:
            import aiohttp
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    def _check_rate_limit(self) -> bool:
        """Check if we're within rate limits."""
        now = time.time()
        
        # Clean old timestamps
        self.order_timestamps = [
            t for t in self.order_timestamps 
            if now - t < 3600
        ]
        
        recent_1m = sum(1 for t in self.order_timestamps if now - t < 60)
        
        return recent_1m < self.orders_per_minute and \
               len(self.order_timestamps) < self.orders_per_hour
    
    def _generate_nonce(self) -> str:
        """Generate unique nonce for order."""
        return str(int(time.time() * 1000)) + str(uuid.uuid4())[:8]
    
    async def place_order(self, market_id: str, side: str,
                         size: float, price: float = None,
                         order_type: str = "LIMIT",
                         time_in_force: str = "GTC",
                         timeout: float = 10.0) -> Order:
        """
        Place an order on Polymarket.
        
        In paper trading mode, simulates order execution.
        """
        if not self._check_rate_limit():
            logger.warning("Rate limit exceeded, throttling order")
            await asyncio.sleep(1)
        
        # Create order request
        order = Order(
            order_id=str(uuid.uuid4()),
            market_id=market_id,
            side=OrderSide(side),
            order_type=OrderType(order_type),
            size=size,
            price=price,
            status=OrderStatus.PENDING,
            timestamp=time.time(),
            nonce=self._generate_nonce()
        )
        
        self.pending_orders[order.order_id] = order
        self.order_timestamps.append(time.time())
        
        if self.paper_trading:
            # Simulate immediate fill at mid price
            await self._simulate_fill(order)
            return order
        
        # Real order placement
        for attempt in range(self.max_retries):
            try:
                result = await self._submit_order(order)
                order.status = OrderStatus.SUBMITTED
                order.nonce = result.get("nonce", order.nonce)
                
                # Wait for fill or timeout
                filled = await self._wait_for_fill(order, timeout)
                if filled:
                    order.status = OrderStatus.FILLED
                    order.filled_size = filled.size
                    order.fill_price = filled.price
                    order.fees = filled.fees
                    self.fills.append(filled)
                
                return order
                
            except APIError as e:
                if e.retryable and attempt < self.max_retries - 1:
                    delay = self.base_delay * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue
                order.status = OrderStatus.REJECTED
                logger.error(f"Order rejected: {e.message}")
                return order
        
        return order
    
    async def _submit_order(self, order: Order) -> dict:
        """Submit order to Polymarket API."""
        session = await self.get_session()
        
        payload = {
            "market_id": order.market_id,
            "side": order.side.value,
            "amount": order.size,
            "nonce": order.nonce
        }
        
        if order.order_type == OrderType.LIMIT:
            payload["price"] = order.price
            payload["order_type"] = "LIMIT"
        else:
            payload["order_type"] = "MARKET"
        
        # Sign order if private key available
        if self.config.private_key:
            payload["signature"] = self._sign_order(order)
        
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        
        try:
            async with session.post(
                f"{self.config.base_url}/order",
                json=payload,
                headers=headers
            ) as resp:
                if resp.status == 429:
                    raise APIError("Rate limited", 429, retryable=True)
                elif resp.status >= 400:
                    error = await resp.text()
                    raise APIError(error, resp.status, retryable=False)
                
                return await resp.json()
                
        except Exception as e:
            raise APIError(str(e), retryable=True)
    
    def _sign_order(self, order: Order) -> str:
        """
        Sign order with private key.
        
        In production, would use proper cryptographic signing.
        """
        # Placeholder - implement actual signing
        return "signature_placeholder"
    
    async def _wait_for_fill(self, order: Order, timeout: float) -> Optional[Fill]:
        """Wait for order to fill or timeout."""
        start = time.time()
        poll_interval = 0.5
        
        while time.time() - start < timeout:
            if order.order_id not in self.pending_orders:
                # Order was cancelled or filled
                return None
            
            try:
                fill = await self._check_order_status(order.order_id)
                if fill:
                    return fill
            except Exception as e:
                logger.warning(f"Fill check error: {e}")
            
            await asyncio.sleep(poll_interval)
        
        # Timeout - order may be partially filled or still open
        logger.info(f"Order {order.order_id} timeout after {timeout}s")
        return None
    
    async def _check_order_status(self, order_id: str) -> Optional[Fill]:
        """Check order status via API."""
        session = await self.get_session()
        
        async with session.get(
            f"{self.config.base_url}/order/{order_id}"
        ) as resp:
            if resp.status == 404:
                return None
            data = await resp.json()
            
            if data.get("status") == "FILLED":
                return Fill(
                    fill_id=data["fill_id"],
                    order_id=order_id,
                    market_id=data["market_id"],
                    side=OrderSide(data["side"]),
                    size=data["filled_size"],
                    price=data["fill_price"],
                    fees=data.get("fees", 0),
                    timestamp=data["timestamp"]
                )
        
        return None
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if order_id not in self.pending_orders:
            return False
        
        order = self.pending_orders[order_id]
        
        try:
            session = await self.get_session()
            async with session.delete(
                f"{self.config.base_url}/order/{order_id}"
            ) as resp:
                if resp.status == 200:
                    order.status = OrderStatus.CANCELLED
                    del self.pending_orders[order_id]
                    return True
                return False
        except Exception as e:
            logger.error(f"Cancel failed: {e}")
            return False
    
    async def cancel_all_for_market(self, market_id: str) -> int:
        """Cancel all pending orders for a market."""
        cancelled = 0
        for order_id in list(self.pending_orders.keys()):
            if self.pending_orders[order_id].market_id == market_id:
                if await self.cancel_order(order_id):
                    cancelled += 1
        return cancelled
    
    async def check_fills(self) -> List[Fill]:
        """Check for fills on pending orders."""
        fills = []
        for order_id in list(self.pending_orders.keys()):
            try:
                if fill := await self._check_order_status(order_id):
                    fills.append(fill)
                    if fill.size >= order.size:
                        del self.pending_orders[order_id]
            except Exception:
                pass
        return fills
    
    async def _simulate_fill(self, order: Order):
        """Simulate order fill for paper trading."""
        # Assume 1% slippage for market orders, 100% fill for limit orders
        if order.order_type == OrderType.MARKET:
            fill_price = order.price * 1.01 if order.side == OrderSide.BUY else order.price * 0.99
        else:
            fill_price = order.price
        
        fill = Fill(
            fill_id=str(uuid.uuid4()),
            order_id=order.order_id,
            market_id=order.market_id,
            side=order.side,
            size=order.size,
            price=fill_price,
            fees=order.size * fill_price * 0.001,  # 0.1% fee
            timestamp=time.time()
        )
        
        order.status = OrderStatus.FILLED
        order.filled_size = order.size
        order.fill_price = fill_price
        order.fees = fill.fees
        
        self.fills.append(fill)
    
    def get_order_history(self, market_id: str = None) -> List[Order]:
        """Get order history, optionally filtered by market."""
        if market_id:
            return [o for o in self.order_history if o.market_id == market_id]
        return list(self.order_history)
    
    def get_fills(self, market_id: str = None) -> List[Fill]:
        """Get fill history."""
        if market_id:
            return [f for f in self.fills if f.market_id == market_id]
        return list(self.fills)
