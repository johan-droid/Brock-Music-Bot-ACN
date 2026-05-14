"""Circuit Breaker pattern implementation for resilient service calls."""

import asyncio
import logging
import time
import random
from enum import Enum
from typing import Optional, Callable, Any, Dict, List
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing, reject fast
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """
    Circuit breaker to prevent cascading failures.

    - CLOSED: Normal operation, calls pass through
    - OPEN: Too many failures, calls rejected immediately
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3,
        expected_exception: type = Exception
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.expected_exception = expected_exception

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self._lock = asyncio.Lock()

        logger.info(
            f"Circuit breaker '{name}' initialized (threshold={failure_threshold}, recovery={recovery_timeout}s)")

    @property
    def is_open(self) -> bool:
        """Check if circuit is open (failing)."""
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if circuit is closed (healthy)."""
        return self.state == CircuitState.CLOSED

    @property
    def is_half_open(self) -> bool:
        """Check if circuit is half-open (testing)."""
        return self.state == CircuitState.HALF_OPEN

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.

        Args:
            func: Async function to call
            *args, **kwargs: Arguments for function

        Returns:
            Function result

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: Original exception if call fails
        """
        async with self._lock:
            await self._update_state()

            if self.state == CircuitState.OPEN:
                raise CircuitBreakerOpen(f"Circuit '{self.name}' is OPEN")

        # Execute the call
        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except self.expected_exception as e:
            await self._record_failure()
            raise

    async def _update_state(self):
        """Update circuit state based on time and failures."""
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure_time and \
               (time.time() - self.last_failure_time) >= self.recovery_timeout:
                logger.info(f"Circuit '{self.name}' entering HALF_OPEN state")
                self.state = CircuitState.HALF_OPEN
                self.failure_count = 0
                self.success_count = 0

    async def _record_success(self):
        """Record successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1

                # If enough successes in half-open, close the circuit
                if self.success_count >= self.half_open_max_calls:
                    logger.info(
                        f"Circuit '{self.name}' recovered, entering CLOSED state")
                    self.state = CircuitState.CLOSED
                    self.failure_count = 0
                    self.success_count = 0
            else:
                # Reset failure count on success in closed state
                if self.failure_count > 0:
                    self.failure_count = 0

    async def _record_failure(self):
        """Record failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # Failed in half-open, go back to open
                logger.warning(
                    f"Circuit '{self.name}' failed in HALF_OPEN, returning to OPEN")
                self.state = CircuitState.OPEN
            elif self.state == CircuitState.CLOSED and \
                    self.failure_count >= self.failure_threshold:
                # Too many failures, open the circuit
                logger.warning(
                    f"Circuit '{self.name}' threshold reached ({self.failure_count}/{self.failure_threshold}), "
                    f"entering OPEN state"
                )
                self.state = CircuitState.OPEN

    def get_status(self) -> dict:
        """Get current circuit breaker status."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "last_failure": self.last_failure_time,
            "is_healthy": self.state == CircuitState.CLOSED
        }


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class CircuitBreakerRegistry:
    """Registry for managing multiple circuit breakers."""

    _breakers: dict[str, CircuitBreaker] = {}

    @classmethod
    def register(
        cls,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        **kwargs
    ) -> CircuitBreaker:
        """Register a new circuit breaker."""
        if name not in cls._breakers:
            cls._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                recovery_timeout=recovery_timeout,
                **kwargs
            )
        return cls._breakers[name]

    @classmethod
    def get(cls, name: str) -> Optional[CircuitBreaker]:
        """Get a circuit breaker by name."""
        return cls._breakers.get(name)

    @classmethod
    def get_all_status(cls) -> dict:
        """Get status of all circuit breakers."""
        return {name: cb.get_status() for name, cb in cls._breakers.items()}

    @classmethod
    def reset(cls, name: str):
        """Reset a circuit breaker to closed state."""
        if name in cls._breakers:
            breaker = cls._breakers[name]
            breaker.state = CircuitState.CLOSED
            breaker.failure_count = 0
            breaker.success_count = 0
            breaker.last_failure_time = None
            logger.info(f"Circuit breaker '{name}' manually reset")


def circuit_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: int = 30,
    fallback_value: Any = None
):
    """
    Decorator to add circuit breaker to an async function.

    Args:
        name: Circuit breaker name
        failure_threshold: Failures before opening
        recovery_timeout: Seconds before half-open
        fallback_value: Value to return on open circuit
    """
    def decorator(func: Callable) -> Callable:
        breaker = CircuitBreakerRegistry.register(
            name=name,
            failure_threshold=failure_threshold,
            recovery_timeout=recovery_timeout
        )

        @wraps(func)
        async def wrapper(*args, **kwargs):
            try:
                return await breaker.call(func, *args, **kwargs)
            except CircuitBreakerOpen:
                if fallback_value is not None:
                    logger.debug(f"Circuit '{name}' open, returning fallback")
                    return fallback_value
                raise

        return wrapper
    return decorator


def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 10.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator to retry async functions with exponential backoff and jitter.

    Args:
        retries: Maximum number of retries
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds
        exceptions: Exceptions that trigger a retry
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == retries:
                        break

                    delay = min(base_delay * (2 ** attempt), max_delay)
                    jitter = random.uniform(0, 0.1 * delay)
                    total_delay = delay + jitter

                    logger.warning(
                        f"Attempt {attempt + 1}/{retries} failed for {func.__name__}: {e}. "
                        f"Retrying in {total_delay:.2f}s"
                    )
                    await asyncio.sleep(total_delay)

            raise last_exception
        return wrapper
    return decorator


class SourceHealthTracker:
    """Tracks health and availability of different music sources to adjust their priorities dynamically."""

    def __init__(self):
        self._sources: Dict[str, Dict[str, Any]] = {
        }
        self._lock = asyncio.Lock()

    async def register_source(self, name: str, base_score: float = 1.0):
        async with self._lock:
            if name not in self._sources:
                self._sources[name] = {
                    "base_score": base_score,
                    "health": 1.0,  # 0.0 to 1.0
                    "failures": 0,
                    "successes": 0,
                    "last_failure": 0,
                    "circuit_open": False
                }

    async def record_success(self, name: str):
        async with self._lock:
            if name in self._sources:
                source = self._sources[name]
                source["successes"] += 1
                source["health"] = min(1.0, source["health"] + 0.1)
                source["failures"] = max(0, source["failures"] - 1)
                source["circuit_open"] = False

    async def record_failure(self, name: str, is_critical: bool = False):
        async with self._lock:
            if name in self._sources:
                source = self._sources[name]
                source["failures"] += 1
                source["last_failure"] = time.time()

                if is_critical:
                    source["health"] = max(0.0, source["health"] - 0.5)
                else:
                    source["health"] = max(0.0, source["health"] - 0.2)

                if source["health"] <= 0.2 or source["failures"] >= 5:
                    source["circuit_open"] = True

    async def get_sorted_sources(self) -> List[str]:
        """Get list of sources sorted by current health and base score."""
        async with self._lock:
            # Check circuit breakers and recovery
            now = time.time()
            for name, source in self._sources.items():
                if source["circuit_open"] and now - source["last_failure"] > 60:
                    # Test recovery after 60 seconds
                    source["circuit_open"] = False
                    source["health"] = 0.5
                    source["failures"] = 0

            # Sort by: not circuit open -> health * base_score
            sorted_sources = sorted(
                self._sources.items(),
                key=lambda x: (not x[1]["circuit_open"],
                               x[1]["health"] * x[1]["base_score"]),
                reverse=True
            )
            return [name for name, _ in sorted_sources]


# Global tracker instance
source_health_tracker = SourceHealthTracker()


# Pre-configured circuit breakers for music services
CIRCUIT_BREAKERS = {
    "deezer": CircuitBreakerRegistry.register(
        "deezer",
        failure_threshold=5,
        recovery_timeout=60
    ),
    "vk": CircuitBreakerRegistry.register(
        "vk",
        failure_threshold=3,
        recovery_timeout=60
    ),
    "database": CircuitBreakerRegistry.register(
        "database",
        failure_threshold=5,
        recovery_timeout=30
    ),
}
