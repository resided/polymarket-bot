"""
Data ingestion layer for Polymarket.
Handles WebSocket connections, REST API calls, and external data sources.
"""

import asyncio
import aiohttp
import json
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime
from dataclasses import dataclass
from urllib.parse import urlencode

from core.config import Config
from core.state import SharedState

logger = logging.getLogger(__name__)


@dataclass
class WebSocketMessage:
    type: str
    market_id: str
    sequence: int
    bids: List
    asks: List
    timestamp: float


class APIClient:
    """REST API client for Polymarket."""
    
    def __init__(self, config: Config):
        self.config = config.api
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limiter = RateLimiter(self.config.rate_limit_rps)
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def request(self, method: str, endpoint: str, 
                     data: dict = None) -> dict:
        async with self.rate_limiter:
            session = await self.get_session()
            url = f"{self.config.base_url}{endpoint}"
            
            headers = {"Content-Type": "application/json"}
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            
            try:
                if method == "GET":
                    async with session.get(url, headers=headers) as resp:
                        return await resp.json()
                elif method == "POST":
                    async with session.post(url, json=data, headers=headers) as resp:
                        return await resp.json()
                elif method == "DELETE":
                    async with session.delete(url, headers=headers) as resp:
                        return await resp.json()
            except aiohttp.ClientError as e:
                logger.error(f"API request failed: {e}")
                raise
    
    async def get_orderbook(self, market_id: str) -> dict:
        return await self.request("GET", f"/book?market_id={market_id}")
    
    async def get_market_price(self, market_id: str) -> dict:
        return await self.request("GET", f"/price?market_id={market_id}")
    
    async def get_midpoint(self, market_id: str) -> dict:
        return await self.request("GET", f"/midpoint?market_id={market_id}")
    
    async def get_markets(self, **params) -> dict:
        query = urlencode(params)
        return await self.request("GET", f"/markets?{query}")
    
    async def get_gamma_markets(self) -> dict:
        async with self.rate_limiter:
            session = await self.get_session()
            async with session.get(self.config.gamma_url + "/markets") as resp:
                return await resp.json()
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class RateLimiter:
    """Token bucket rate limiter."""
    
    def __init__(self, rate_per_second: int):
        self.rate = rate_per_second
        self.tokens = rate_per_second
        self.last_update = asyncio.get_event_loop().time()
        self.lock = asyncio.Lock()
    
    async def __aenter__(self):
        async with self.lock:
            now = asyncio.get_event_loop().time()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1
    
    async def __aexit__(self, *args):
        pass


class WebSocketManager:
    """WebSocket connection manager for real-time market data."""
    
    def __init__(self, config: Config, state: SharedState):
        self.config = config
        self.state = state
        self.ws_url = config.api.wss_url
        self.session: Optional[aiohttp.ClientSession] = None
        self.ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.running = False
        self.reconnect_delay = 1.0
        self.max_reconnect_delay = 60.0
        self.sequence_numbers: Dict[str, int] = {}
        self.handlers: List[Callable] = []
    
    async def connect(self):
        """Establish WebSocket connection."""
        self.session = aiohttp.ClientSession()
        
        while self.running:
            try:
                self.ws = await self.session.ws_connect(
                    self.ws_url,
                    heartbeat=30
                )
                
                # Subscribe to markets
                await self.subscribe(self.config.market_ids)
                
                logger.info("WebSocket connected")
                self.reconnect_delay = 1.0
                
                # Start receiving messages
                await self.receive_loop()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                await asyncio.sleep(self.reconnect_delay)
                self.reconnect_delay = min(
                    self.reconnect_delay * 2, 
                    self.max_reconnect_delay
                )
    
    async def subscribe(self, market_ids: List[str]):
        """Subscribe to market updates."""
        if self.ws:
            await self.ws.send_json({
                "type": "subscribe",
                "channel": "market",
                "market_ids": market_ids,
                "snapshot": True
            })
    
    async def receive_loop(self):
        """Receive and process WebSocket messages."""
        async for msg in self.ws:
            if not self.running:
                break
            
            try:
                data = json.loads(msg.data)
                await self.handle_message(data)
            except Exception as e:
                logger.error(f"Message handling error: {e}")
    
    async def handle_message(self, data: dict):
        """Process incoming WebSocket message."""
        msg_type = data.get("type")
        
        if msg_type == "snapshot":
            self._handle_snapshot(data)
        elif msg_type == "update":
            self._handle_update(data)
        elif msg_type == "pong":
            # Heartbeat response
            pass
    
    def _handle_snapshot(self, data: dict):
        """Handle full order book snapshot."""
        market_id = data.get("market_id")
        self.sequence_numbers[market_id] = data.get("sequence", 0)
        
        self.state.update_book(
            market_id=market_id,
            bids=data.get("bids", []),
            asks=data.get("asks", []),
            sequence=data["sequence"],
            timestamp=data.get("timestamp", 0)
        )
    
    def _handle_update(self, data: dict):
        """Handle order book update."""
        market_id = data.get("market_id")
        sequence = data.get("sequence", 0)
        
        # Check for sequence gap
        expected = self.sequence_numbers.get(market_id, 0)
        if sequence != expected + 1:
            logger.warning(
                f"Sequence gap for {market_id}: "
                f"expected {expected + 1}, got {sequence}"
            )
            # Request snapshot to resync
            # In production, would trigger snapshot refresh
        
        self.sequence_numbers[market_id] = sequence
        
        self.state.update_book(
            market_id=market_id,
            bids=data.get("bids", []),
            asks=data.get("asks", []),
            sequence=sequence,
            timestamp=data.get("timestamp", 0)
        )
    
    async def close(self):
        """Close WebSocket connection."""
        self.running = False
        if self.ws:
            await self.ws.close()
        if self.session:
            await self.session.close()


class ExternalDataFetcher:
    """Fetch external probability data from various sources."""
    
    def __init__(self, config: Config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, dict] = {}
    
    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self.session = aiohttp.ClientSession(timeout=timeout)
        return self.session
    
    async def fetch_fivethirtyeight(self) -> Dict[str, float]:
        """Fetch 2024 election probabilities (simplified)."""
        # In production, parse actual 538 page or API
        try:
            session = await self.get_session()
            # Placeholder - would parse actual 538 data
            return {
                "dem_president": 0.52,
                "rep_president": 0.48
            }
        except Exception as e:
            logger.error(f"Failed to fetch 538 data: {e}")
            return {}
    
    async def fetch_sportsbook_odds(self, sport: str = "nfl") -> Dict[str, float]:
        """Fetch sportsbook odds via The Odds API."""
        api_key = self.config.external_sources.get("sportsbook", {}).get("api_key")
        if not api_key:
            return {}
        
        try:
            session = await self.get_session()
            url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds"
            params = {"apiKey": api_key, "regions": "us"}
            
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                
                odds = {}
                for event in data[:5]:  # Process top 5 events
                    for outcome in event.get("bookmakers", [{}])[0].get("markets", [{}])[0].get("outcomes", []):
                        name = outcome.get("name")
                        price = outcome.get("price")
                        if name and price:
                            implied_prob = 1 / price if price > 0 else 0
                            odds[f"{event['id']}_{name}"] = implied_prob
                
                return odds
        except Exception as e:
            logger.error(f"Failed to fetch sportsbook odds: {e}")
            return {}
    
    async def fetch_kalshi_odds(self) -> Dict[str, float]:
        """Fetch odds from Kalshi prediction market."""
        try:
            session = await self.get_session()
            async with session.get("https://api.kalshi.com/v1/markets") as resp:
                data = await resp.json()
                
                odds = {}
                for market in data.get("markets", []):
                    market_id = market.get("id")
                    for outcome in market.get("outcomes", []):
                        odds[f"{market_id}_{outcome['ticker']}"] = outcome.get("probability", 0)
                
                return odds
        except Exception as e:
            logger.error(f"Failed to fetch Kalshi data: {e}")
            return {}
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class DataIngestionManager:
    """Main data ingestion coordinator."""
    
    def __init__(self, config: Config, state: SharedState):
        self.config = config
        self.state = state
        self.ws_manager = WebSocketManager(config, state)
        self.api_client = APIClient(config)
        self.external_fetcher = ExternalDataFetcher(config)
        self.running = False
    
    async def run(self):
        """Start all data ingestion."""
        self.running = True
        
        # Start WebSocket
        ws_task = asyncio.create_task(self.ws_manager.connect())
        
        # Fetch market metadata
        await self.load_market_metadata()
        
        # Start external data polling
        external_task = asyncio.create_task(self.external_data_loop())
        
        await asyncio.gather(ws_task, external_task)
    
    async def load_market_metadata(self):
        """Load market relationships and metadata."""
        try:
            # Get active trading markets from CLOB
            clob_markets = await self.api_client.get_markets()
            active_market_ids = []
            
            if isinstance(clob_markets, list):
                for market in clob_markets[:50]:  # Limit to top 50 markets
                    market_id = market.get("condition_id") or market.get("id")
                    if market_id and market.get("active", True):
                        active_market_ids.append(market_id)
                        logger.info(f"Found active CLOB market: {market_id}")
            
            # Update config with discovered markets
            if active_market_ids:
                self.config.market_ids.extend(active_market_ids)
                logger.info(f"Added {len(active_market_ids)} markets to monitoring")
            
            # Get market metadata from Gamma
            markets = await self.api_client.get_gamma_markets()
            
            market_list = markets if isinstance(markets, list) else markets.get("markets", [])
            for market in market_list:
                market_id = market.get("id")
                
                # Store related markets based on event
                event_id = market.get("event_id")
                if event_id:
                    # Group markets by event
                    self.state.set_related_markets(market_id, [])
                    
        except Exception as e:
            logger.error(f"Failed to load market metadata: {e}")
    
    async def update_external_signals(self, mispricing_engine):
        """Update external signals and feed to mispricing engine."""
        try:
            # Fetch external data
            fte_data = await self.external_fetcher.fetch_fivethirtyeight()
            for source, prob in fte_data.items():
                # Map to Polymarket markets (would need proper mapping)
                self.state.update_external_signal(
                    market_id=f"election_{source}",
                    source="fivethirtyeight",
                    probability=prob,
                    timestamp=asyncio.get_event_loop().time()
                )
        except Exception as e:
            logger.error(f"External data update failed: {e}")
    
    async def external_data_loop(self):
        """Periodically fetch external data."""
        interval = self.config.external_sources.get("sportsbook", {}).get("poll_interval", 60)
        
        while self.running:
            try:
                await self.update_external_signals(None)
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"External data loop error: {e}")
                await asyncio.sleep(10)
    
    async def stop(self):
        """Stop data ingestion."""
        self.running = False
        await self.ws_manager.close()
        await self.api_client.close()
        await self.external_fetcher.close()
