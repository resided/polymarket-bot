"""
Configuration management for Polymarket Trading Bot.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class RiskConfig:
    max_exposure_per_market: float = 0.05
    max_exposure_per_outcome: float = 0.10
    max_correlated_exposure: float = 0.15
    max_drawdown_limit: float = 0.15
    kill_switch_threshold: float = 0.20
    default_stop_loss: float = 0.25
    trailing_stop: float = 0.15


@dataclass
class APIConfig:
    api_key: str = ""
    private_key: str = ""
    base_url: str = "https://clob.polymarket.com"
    wss_url: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    gamma_url: str = "https://gamma-api.polymarket.com"
    timeout: float = 10.0
    rate_limit_rps: int = 100


@dataclass
class Config:
    # Strategy settings
    enable_arb: bool = True
    enable_mispricing: bool = True
    enable_micro: bool = True
    min_edge: float = 0.005  # 50 bps
    fee_rate: float = 0.001
    
    # Capital
    initial_capital: float = 100000
    max_capital_per_trade: float = 5000
    
    # Risk
    risk: RiskConfig = field(default_factory=RiskConfig)
    
    # API
    api: APIConfig = field(default_factory=APIConfig)
    
    # Markets to watch
    market_ids: List[str] = field(default_factory=list)
    related_markets: Dict[str, List[str]] = field(default_factory=dict)
    
    # External data
    external_sources: Dict[str, Dict] = field(default_factory=dict)
    
    # Server
    port: int = 8000
    metrics_port: int = 9090
    
    # Logging
    log_level: str = "INFO"
    
    # Paper mode
    paper_trading: bool = False
    
    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        risk_data = data.get("risk", {})
        api_data = data.get("api", {})
        
        return cls(
            enable_arb=data.get("enable_arb", True),
            enable_mispricing=data.get("enable_mispricing", True),
            enable_micro=data.get("enable_micro", True),
            min_edge=data.get("min_edge", 0.005),
            fee_rate=data.get("fee_rate", 0.001),
            initial_capital=data.get("initial_capital", 100000),
            max_capital_per_trade=data.get("max_capital_per_trade", 5000),
            risk=RiskConfig(**risk_data) if risk_data else RiskConfig(),
            api=APIConfig(
                api_key=api_data.get("api_key", ""),
                private_key=api_data.get("private_key", ""),
                base_url=api_data.get("base_url", "https://clob.polymarket.com"),
                wss_url=api_data.get("wss_url", "wss://ws-subscriptions-clob.polymarket.com/ws/market")
            ),
            market_ids=data.get("market_ids", []),
            related_markets=data.get("related_markets", {}),
            external_sources=data.get("external_sources", {}),
            port=data.get("port", 8000),
            metrics_port=data.get("metrics_port", 9090),
            log_level=data.get("log_level", "INFO"),
            paper_trading=data.get("paper_trading", False)
        )


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file and environment."""
    load_dotenv()
    
    # Try config file first
    if config_path is None:
        config_path = os.environ.get("CONFIG_PATH", "config.yaml")
    
    config_data = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            config_data = yaml.safe_load(f) or {}
    
    # Override with environment variables
    if os.environ.get("POLYMARKET_API_KEY"):
        config_data.setdefault("api", {})["api_key"] = os.environ["POLYMARKET_API_KEY"]
    if os.environ.get("POLYMARKET_PRIVATE_KEY"):
        config_data.setdefault("api", {})["private_key"] = os.environ["POLYMARKET_PRIVATE_KEY"]
    if os.environ.get("REDIS_URL"):
        config_data.setdefault("redis_url", os.environ["REDIS_URL"])
    if os.environ.get("LOG_LEVEL"):
        config_data["log_level"] = os.environ["LOG_LEVEL"]
    if os.environ.get("ENABLE_ARB"):
        config_data["enable_arb"] = os.environ["ENABLE_ARB"].lower() == "true"
    if os.environ.get("ENABLE_MISPRICING"):
        config_data["enable_mispricing"] = os.environ["ENABLE_MISPRICING"].lower() == "true"
    if os.environ.get("ENABLE_MICRO"):
        config_data["enable_micro"] = os.environ["ENABLE_MICRO"].lower() == "true"
    if os.environ.get("PAPER_TRADING"):
        config_data["paper_trading"] = os.environ["PAPER_TRADING"].lower() == "true"
    if os.environ.get("MAX_CAPITAL_PER_TRADE"):
        config_data["max_capital_per_trade"] = float(os.environ["MAX_CAPITAL_PER_TRADE"])
    
    return Config.from_dict(config_data)


# Default config file content
DEFAULT_CONFIG = """
# Polymarket Trading Bot Configuration
# Copy this to config.yaml and customize

# API Configuration
api:
  api_key: "your_api_key_here"
  private_key: "your_private_key_here"
  base_url: "https://clob.polymarket.com"
  wss_url: "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Strategy Settings
enable_arb: true
enable_mispricing: true
enable_micro: true
min_edge: 0.005  # 50 bps minimum edge
fee_rate: 0.001  # 0.1% fee

# Capital
initial_capital: 100000
max_capital_per_trade: 5000

# Risk Management
risk:
  max_exposure_per_market: 0.05
  max_exposure_per_outcome: 0.10
  max_correlated_exposure: 0.15
  max_drawdown_limit: 0.15
  kill_switch_threshold: 0.20
  default_stop_loss: 0.25
  trailing_stop: 0.15

# Markets to watch (add your market IDs)
market_ids: []
# Example related markets:
# related_markets:
#   "0x...market1": ["0x...market2", "0x...market3"]

# External Data Sources
external_sources:
  fivethirtyeight:
    enabled: true
    url: "https://projects.fivethirtyeight.com/2024-election-forecast/"
    poll_interval: 300
  sportsbook:
    enabled: true
    url: "https://api.the-odds-api.com/v4/sports/"
    api_key: "your_odds_api_key"
    poll_interval: 60

# Server Configuration
port: 8000
metrics_port: 9090
log_level: "INFO"

# Paper Trading (no real orders)
paper_trading: false
"""
