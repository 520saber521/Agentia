from dataclasses import dataclass, field
from typing import List


@dataclass
class RouterConfig:
    ack_timeout_ms: int = 120000
    retry_backoff_ms: List[int] = field(
        default_factory=lambda: [30000, 120000, 300000, 600000, 600000]
    )
    max_retries: int = 5
    default_ttl_ms: int = 3600000
    jitter_ratio: float = 0.2
    retry_poll_interval_ms: int = 500
    presence_interval_ms: int = 30000
    presence_timeout_multiplier: int = 2
