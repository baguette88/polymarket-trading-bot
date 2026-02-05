"""
Order Execution Module

Handles order placement, verification, and retry logic.
Separates execution concerns from strategy logic.
"""
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """Result of an order execution attempt."""
    success: bool
    order_id: Optional[str] = None
    tx_hash: Optional[str] = None
    filled_size: float = 0
    filled_price: float = 0
    error: Optional[str] = None
    metadata: Optional[Dict] = None


class OrderExecutor:
    """
    Handles order execution with retry logic and verification.

    Responsibilities:
    - Pre-trade validation (price, spread, size)
    - Order placement with retries
    - Fill verification
    - Execution logging
    """

    def __init__(self, client, config: Optional[Dict] = None):
        """
        Args:
            client: PolymarketClient instance.
            config: Execution configuration.
        """
        self.client = client
        self.config = config or {}

        # Execution parameters
        self.max_retries = self.config.get('max_retries', 3)
        self.retry_delay = self.config.get('retry_delay', 2)
        self.verify_timeout = self.config.get('verify_timeout', 30)
        self.max_spread = self.config.get('max_spread', 0.10)
        self.max_entry_price = self.config.get('max_entry_price', 0.60)

    def execute_buy(
        self,
        token_id: str,
        amount_usd: float,
        max_price: Optional[float] = None
    ) -> ExecutionResult:
        """
        Execute a market buy order.

        Args:
            token_id: Token to buy.
            amount_usd: Dollar amount to spend.
            max_price: Maximum acceptable price.

        Returns:
            ExecutionResult with fill details or error.
        """
        max_price = max_price or self.max_entry_price

        # Pre-flight checks
        try:
            book = self.client.get_orderbook(token_id)
        except Exception as e:
            return ExecutionResult(success=False, error=f"Orderbook fetch failed: {e}")

        # Validate spread
        if book['spread'] > self.max_spread:
            return ExecutionResult(
                success=False,
                error=f"Spread too wide: {book['spread']:.2%} > {self.max_spread:.2%}"
            )

        # Validate price
        if book['ask'] > max_price:
            return ExecutionResult(
                success=False,
                error=f"Ask {book['ask']:.2f} exceeds max {max_price:.2f}"
            )

        # Calculate size
        entry_price = book['ask']
        size = amount_usd / entry_price

        log.info(f"Executing buy: {size:.2f} shares @ ${entry_price:.3f} = ${amount_usd:.2f}")

        # Execute with retries
        return self._execute_with_retry(token_id, entry_price, size, 'buy')

    def execute_sell(
        self,
        token_id: str,
        size: float,
        min_price: Optional[float] = None
    ) -> ExecutionResult:
        """
        Execute a market sell order.

        Args:
            token_id: Token to sell.
            size: Number of shares to sell.
            min_price: Minimum acceptable price.

        Returns:
            ExecutionResult with fill details or error.
        """
        min_price = min_price or 0.01

        try:
            book = self.client.get_orderbook(token_id)
        except Exception as e:
            return ExecutionResult(success=False, error=f"Orderbook fetch failed: {e}")

        if book['bid'] < min_price:
            return ExecutionResult(
                success=False,
                error=f"Bid {book['bid']:.2f} below min {min_price:.2f}"
            )

        exit_price = book['bid']
        log.info(f"Executing sell: {size:.2f} shares @ ${exit_price:.3f}")

        return self._execute_with_retry(token_id, exit_price, size, 'sell')

    def _execute_with_retry(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str
    ) -> ExecutionResult:
        """Execute order with exponential backoff retry."""
        last_error = None

        for attempt in range(self.max_retries):
            try:
                order = self.client.create_order(
                    token_id=token_id,
                    price=price,
                    size=size,
                    side=side
                )

                order_id = order.get('orderID') or order.get('id')

                if not order_id:
                    log.warning(f"No order ID in response: {order}")
                    continue

                # Verify fill
                result = self._verify_fill(order_id)
                if result.success:
                    return result

            except Exception as e:
                last_error = str(e)
                log.warning(f"Attempt {attempt + 1} failed: {e}")

            # Exponential backoff
            if attempt < self.max_retries - 1:
                wait = self.retry_delay * (2 ** attempt)
                log.info(f"Retrying in {wait}s...")
                time.sleep(wait)

        return ExecutionResult(
            success=False,
            error=f"All {self.max_retries} attempts failed. Last error: {last_error}"
        )

    def _verify_fill(self, order_id: str) -> ExecutionResult:
        """Wait for and verify order fill."""
        start = time.time()

        while time.time() - start < self.verify_timeout:
            try:
                order = self.client.get_order(order_id)
                status = order.get('status', '').upper()

                if status == 'MATCHED':
                    return ExecutionResult(
                        success=True,
                        order_id=order_id,
                        tx_hash=order.get('transactionHash'),
                        filled_size=float(order.get('size_matched', 0)),
                        filled_price=float(order.get('price', 0)),
                        metadata=order
                    )

                elif status in ['CANCELLED', 'EXPIRED', 'FAILED']:
                    return ExecutionResult(
                        success=False,
                        order_id=order_id,
                        error=f"Order {status}"
                    )

            except Exception as e:
                log.warning(f"Verification check failed: {e}")

            time.sleep(2)

        return ExecutionResult(
            success=False,
            order_id=order_id,
            error=f"Verification timeout after {self.verify_timeout}s"
        )
