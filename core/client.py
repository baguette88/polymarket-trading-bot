"""
Polymarket API Client Wrapper

Handles authentication, market discovery, and low-level API calls.
This module wraps py-clob-client with additional error handling and logging.
"""
import os
import logging
from typing import Optional, Dict, Any, List

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs
    from py_clob_client.order_builder.constants import BUY, SELL
    PY_CLOB_AVAILABLE = True
except ImportError:
    PY_CLOB_AVAILABLE = False
    ClobClient = None

log = logging.getLogger(__name__)


class PolymarketClient:
    """
    Wrapper around py-clob-client for Polymarket trading.

    Responsibilities:
    - Authentication and wallet management
    - Market/orderbook queries
    - Low-level order creation (execution handled by OrderExecutor)
    """

    CLOB_HOST = "https://clob.polymarket.com"
    GAMMA_HOST = "https://gamma-api.polymarket.com"
    CHAIN_ID = 137  # Polygon mainnet

    def __init__(self, private_key: Optional[str] = None):
        """
        Initialize the client.

        Args:
            private_key: Wallet private key. If None, reads from environment.
        """
        if not PY_CLOB_AVAILABLE:
            raise ImportError(
                "py-clob-client not installed. Run: pip install py-clob-client"
            )

        self.private_key = private_key or os.environ.get('POLYGON_WALLET_PRIVATE_KEY')
        if not self.private_key:
            raise ValueError("No private key provided")

        self._client = None
        self._initialized = False

    def connect(self) -> bool:
        """
        Initialize connection and API credentials.

        Returns:
            True if successful, False otherwise.
        """
        try:
            self._client = ClobClient(
                host=self.CLOB_HOST,
                key=self.private_key,
                chain_id=self.CHAIN_ID
            )

            # Derive API credentials
            self._client.set_api_creds(self._client.create_or_derive_api_creds())
            self._initialized = True

            log.info("Polymarket client connected successfully")
            return True

        except Exception as e:
            log.error(f"Failed to connect: {e}")
            return False

    def setup_allowances(self) -> bool:
        """
        Set up USDC allowances for trading.
        Only needs to be done once per wallet.

        Returns:
            True if successful.
        """
        if not self._initialized:
            raise RuntimeError("Client not connected")

        try:
            self._client.set_allowances()
            log.info("Allowances set successfully")
            return True
        except Exception as e:
            log.error(f"Failed to set allowances: {e}")
            return False

    def get_orderbook(self, token_id: str) -> Dict[str, Any]:
        """
        Fetch orderbook for a token.

        Args:
            token_id: The token to query.

        Returns:
            Dict with bids, asks, and calculated metrics.
        """
        if not self._initialized:
            raise RuntimeError("Client not connected")

        book = self._client.get_order_book(token_id)

        # Calculate useful metrics
        best_bid = float(book['bids'][0]['price']) if book.get('bids') else 0
        best_ask = float(book['asks'][0]['price']) if book.get('asks') else 1

        return {
            'raw': book,
            'bid': best_bid,
            'ask': best_ask,
            'spread': round(best_ask - best_bid, 4),
            'mid': round((best_bid + best_ask) / 2, 4),
            'bid_depth': sum(float(b['size']) for b in book.get('bids', [])[:5]),
            'ask_depth': sum(float(a['size']) for a in book.get('asks', [])[:5])
        }

    def get_market(self, condition_id: str) -> Dict[str, Any]:
        """
        Fetch market details from Gamma API.

        Args:
            condition_id: The market condition ID.

        Returns:
            Market details including resolution status.
        """
        import requests

        url = f"{self.GAMMA_HOST}/markets/{condition_id}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()

    def search_markets(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for markets by keyword.

        Args:
            query: Search term.
            limit: Max results.

        Returns:
            List of matching markets.
        """
        import requests

        url = f"{self.GAMMA_HOST}/markets"
        params = {'search': query, 'limit': limit, 'active': True}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    def create_order(self, token_id: str, price: float, size: float,
                     side: str = 'buy') -> Dict[str, Any]:
        """
        Create and post an order.

        Args:
            token_id: Token to trade.
            price: Limit price (0-1).
            size: Number of shares.
            side: 'buy' or 'sell'.

        Returns:
            Order response from API.
        """
        if not self._initialized:
            raise RuntimeError("Client not connected")

        order_side = BUY if side.lower() == 'buy' else SELL

        order = self._client.create_and_post_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side
            )
        )
        return order

    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch order status by ID."""
        if not self._initialized:
            raise RuntimeError("Client not connected")
        return self._client.get_order(order_id)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not self._initialized:
            raise RuntimeError("Client not connected")
        try:
            self._client.cancel(order_id)
            return True
        except Exception as e:
            log.warning(f"Cancel failed: {e}")
            return False

    def get_positions(self) -> List[Dict]:
        """Get all open positions for this wallet."""
        import requests

        wallet = self._client.get_address()
        url = f"https://data-api.polymarket.com/positions"
        params = {'user': wallet}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        return response.json()

    @property
    def wallet_address(self) -> str:
        """Get the connected wallet address."""
        if not self._initialized:
            raise RuntimeError("Client not connected")
        return self._client.get_address()
