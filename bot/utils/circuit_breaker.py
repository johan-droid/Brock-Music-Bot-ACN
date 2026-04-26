"""Circuit Breaker pattern implementation for resilient service calls."""

import asyncio
import logging
import time
from enum import Enum
from typing import Optional, Callable, Any
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing, reject fast
    HALF_OPEN = "half_open" # Testing if recovered


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
        
        logger.info(f"Circuit breaker '{name}' initialized (threshold={failure_threshold}, recovery={recovery_timeout}s)")
    
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
                    logger.info(f"Circuit '{self.name}' recovered, entering CLOSED state")
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
                logger.warning(f"Circuit '{self.name}' failed in HALF_OPEN, returning to OPEN")
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


# Pre-configured circuit breakers for music services
CIRCUIT_BREAKERS = {
    "jiosaavn": CircuitBreakerRegistry.register(
        "jiosaavn",
        failure_threshold=3,
        recovery_timeout=60
    ),
    "jiosaavn_wrapper": CircuitBreakerRegistry.register(
        "jiosaavn_wrapper",
        failure_threshold=3,
        recovery_timeout=30
    ),
    "youtube": CircuitBreakerRegistry.register(
        "youtube",
        failure_threshold=5,
        recovery_timeout=120
    ),
    "youtube_wrapper": CircuitBreakerRegistry.register(
        "youtube_wrapper",
        failure_threshold=3,
        recovery_timeout=30
    ),
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
