"""
State Management Module

Handles persistent state for trades, P&L, and bot metadata.
Uses JSON for simplicity and human-readability.
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from uuid import uuid4

log = logging.getLogger(__name__)


@dataclass
class Trade:
    """Represents a single trade."""
    id: str
    timestamp: str
    market_id: str
    token_id: str
    direction: str          # 'long' or 'short'
    outcome: str            # 'YES' or 'NO'
    entry_price: float
    size: float             # shares
    amount_usd: float       # cost
    order_id: Optional[str] = None
    tx_hash: Optional[str] = None
    strategy: str = 'default'

    # Resolution fields (filled later)
    resolved: bool = False
    result: Optional[str] = None    # 'win' or 'loss'
    pnl: Optional[float] = None
    resolution_time: Optional[str] = None

    @classmethod
    def create(cls, **kwargs) -> 'Trade':
        """Factory method with auto-generated ID and timestamp."""
        return cls(
            id=str(uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            **kwargs
        )

    def to_dict(self) -> Dict:
        return asdict(self)


class StateManager:
    """
    Manages persistent bot state.

    Features:
    - Atomic saves (write to temp, then rename)
    - Auto-backup before changes
    - Trade history with P&L tracking
    - Deduplication tracking
    """

    def __init__(self, state_file: str = 'state.json', backup_dir: str = 'backups'):
        self.state_file = Path(state_file)
        self.backup_dir = Path(backup_dir)
        self.backup_dir.mkdir(exist_ok=True)

        self._state = self._load()

    def _default_state(self) -> Dict:
        """Default state structure."""
        return {
            'version': 1,
            'created': datetime.now(timezone.utc).isoformat(),
            'trades': [],
            'totals': {
                'pnl': 0.0,
                'wins': 0,
                'losses': 0,
                'total_trades': 0
            },
            'tracking': {
                'last_signal': None,
                'last_market_id': None,
                'last_trade_time': None
            },
            'metadata': {}
        }

    def _load(self) -> Dict:
        """Load state from file or create default."""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    state = json.load(f)
                log.info(f"Loaded state: {state['totals']['total_trades']} trades")
                return state
            except (json.JSONDecodeError, KeyError) as e:
                log.warning(f"State file corrupted, starting fresh: {e}")

        return self._default_state()

    def save(self):
        """Save state atomically."""
        self._state['last_saved'] = datetime.now(timezone.utc).isoformat()

        # Write to temp file first
        temp_file = self.state_file.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(self._state, f, indent=2, default=str)

        # Atomic rename
        temp_file.rename(self.state_file)
        log.debug("State saved")

    def backup(self, reason: str = 'manual'):
        """Create a backup of current state."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_file = self.backup_dir / f"state_{timestamp}_{reason}.json"

        with open(backup_file, 'w') as f:
            json.dump(self._state, f, indent=2, default=str)

        log.info(f"Backup created: {backup_file}")

    def add_trade(self, trade: Trade):
        """Add a new trade to history."""
        self._state['trades'].append(trade.to_dict())
        self._state['totals']['total_trades'] += 1
        self._state['tracking']['last_trade_time'] = trade.timestamp
        self._state['tracking']['last_market_id'] = trade.market_id
        self.save()

    def resolve_trade(self, trade_id: str, result: str, pnl: float):
        """
        Mark a trade as resolved.

        Args:
            trade_id: The trade's unique ID.
            result: 'win' or 'loss'.
            pnl: Profit/loss amount.
        """
        for trade in self._state['trades']:
            if trade['id'] == trade_id:
                trade['resolved'] = True
                trade['result'] = result
                trade['pnl'] = round(pnl, 4)
                trade['resolution_time'] = datetime.now(timezone.utc).isoformat()

                # Update totals
                self._state['totals']['pnl'] += pnl
                if result == 'win':
                    self._state['totals']['wins'] += 1
                else:
                    self._state['totals']['losses'] += 1

                self.save()
                log.info(f"Trade {trade_id} resolved: {result} ({pnl:+.2f})")
                return

        log.warning(f"Trade {trade_id} not found for resolution")

    def get_unresolved_trades(self) -> List[Dict]:
        """Get all trades pending resolution."""
        return [t for t in self._state['trades'] if not t.get('resolved', False)]

    def get_recent_trades(self, limit: int = 10) -> List[Dict]:
        """Get most recent trades."""
        return self._state['trades'][-limit:]

    def already_traded_market(self, market_id: str) -> bool:
        """Check if we've already traded this market."""
        return self._state['tracking'].get('last_market_id') == market_id

    def set_last_signal(self, signal: Optional[str]):
        """Track the last signal for reset detection."""
        self._state['tracking']['last_signal'] = signal
        self.save()

    def get_last_signal(self) -> Optional[str]:
        return self._state['tracking'].get('last_signal')

    @property
    def totals(self) -> Dict:
        return self._state['totals']

    @property
    def pnl(self) -> float:
        return self._state['totals']['pnl']

    @property
    def win_rate(self) -> float:
        wins = self._state['totals']['wins']
        losses = self._state['totals']['losses']
        total = wins + losses
        return wins / total if total > 0 else 0

    def set_metadata(self, key: str, value: Any):
        """Store arbitrary metadata."""
        self._state['metadata'][key] = value
        self.save()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self._state['metadata'].get(key, default)
