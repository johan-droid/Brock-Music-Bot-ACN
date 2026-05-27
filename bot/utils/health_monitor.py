"""Health monitoring and checks for all bot services."""

import asyncio
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from bot.utils.circuit_breaker import CircuitBreakerRegistry

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health check status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a health check."""

    service: str
    status: HealthStatus
    response_time_ms: float
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class HealthChecker:
    """Health checker for monitoring all bot services."""

    def __init__(self):
        self._checks: Dict[str, callable] = {}
        self._last_results: Dict[str, HealthCheckResult] = {}
        self._check_interval = 60
        self._monitoring_task: Optional[asyncio.Task] = None

    def register_check(self, name: str, check_func: callable):
        self._checks[name] = check_func
        logger.info(f"Health check registered: {name}")

    async def run_check(self, name: str) -> HealthCheckResult:
        if name not in self._checks:
            return HealthCheckResult(
                service=name,
                status=HealthStatus.UNKNOWN,
                response_time_ms=0,
                message="Check not registered",
            )

        start_time = time.time()
        try:
            result = await asyncio.wait_for(self._checks[name](), timeout=10.0)
            response_time = (time.time() - start_time) * 1000

            if isinstance(result, HealthCheckResult):
                result.response_time_ms = response_time
                self._last_results[name] = result
                return result

            status = HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY
            check_result = HealthCheckResult(
                service=name,
                status=status,
                response_time_ms=response_time,
                message="OK" if result else "Check failed",
            )
            self._last_results[name] = check_result
            return check_result

        except asyncio.TimeoutError:
            response_time = (time.time() - start_time) * 1000
            check_result = HealthCheckResult(
                service=name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                message="Health check timeout",
            )
            self._last_results[name] = check_result
            return check_result
        except Exception as e:
            response_time = (time.time() - start_time) * 1000
            check_result = HealthCheckResult(
                service=name,
                status=HealthStatus.UNHEALTHY,
                response_time_ms=response_time,
                message=f"Check error: {str(e)}",
            )
            self._last_results[name] = check_result
            return check_result

    async def run_all_checks(self) -> Dict[str, HealthCheckResult]:
        tasks = [self.run_check(name) for name in self._checks.keys()]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for name, result in zip(self._checks.keys(), results):
            if isinstance(result, Exception):
                self._last_results[name] = HealthCheckResult(
                    service=name,
                    status=HealthStatus.UNHEALTHY,
                    response_time_ms=0,
                    message=f"Check exception: {str(result)}",
                )

        return self._last_results

    def get_overall_status(self) -> Dict[str, Any]:
        if not self._last_results:
            return {
                "status": HealthStatus.UNKNOWN.value,
                "healthy_count": 0,
                "total_count": 0,
                "timestamp": time.time(),
            }

        healthy = sum(1 for r in self._last_results.values() if r.status == HealthStatus.HEALTHY)
        degraded = sum(1 for r in self._last_results.values() if r.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for r in self._last_results.values() if r.status == HealthStatus.UNHEALTHY)

        if unhealthy > 0:
            overall = HealthStatus.DEGRADED if healthy > unhealthy else HealthStatus.UNHEALTHY
        elif degraded > 0:
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return {
            "status": overall.value,
            "healthy_count": healthy,
            "degraded_count": degraded,
            "unhealthy_count": unhealthy,
            "total_count": len(self._last_results),
            "timestamp": time.time(),
        }

    async def start_monitoring(self):
        if self._monitoring_task is not None:
            return

        async def monitor_loop():
            while True:
                try:
                    await self.run_all_checks()
                    await asyncio.sleep(self._check_interval)
                except Exception as e:
                    logger.error(f"Health monitoring error: {e}")
                    await asyncio.sleep(self._check_interval)

        self._monitoring_task = asyncio.create_task(monitor_loop())
        logger.info("Health monitoring started")

    def stop_monitoring(self):
        if self._monitoring_task:
            self._monitoring_task.cancel()
            self._monitoring_task = None
            logger.info("Health monitoring stopped")


health_checker = HealthChecker()


async def check_music_microservice() -> HealthCheckResult:
    start_time = time.time()
    try:
        from bot.core.music_backend import music_backend
        health = await music_backend.health()
        response_time = (time.time() - start_time) * 1000

        if health.get("healthy"):
            return HealthCheckResult(
                service="music_microservice",
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
                message="Service healthy",
                details=health,
            )

        return HealthCheckResult(
            service="music_microservice",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=response_time,
            message="No healthy microservice endpoint reported",
            details=health,
        )
    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return HealthCheckResult(
            service="music_microservice",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=response_time,
            message=str(e),
        )


async def check_database() -> HealthCheckResult:
    start_time = time.time()
    try:
        from bot.utils.neon_db import neon_db

        if neon_db:
            if hasattr(neon_db, "health_check") and neon_db.health_check():
                response_time = (time.time() - start_time) * 1000
                return HealthCheckResult(
                    service="database",
                    status=HealthStatus.HEALTHY,
                    response_time_ms=response_time,
                    message="Neon DB connected",
                )

        from bot.utils.supabase_db import supabase_db

        if supabase_db.client:
            response_time = (time.time() - start_time) * 1000
            return HealthCheckResult(
                service="database",
                status=HealthStatus.HEALTHY,
                response_time_ms=response_time,
                message="Supabase connected",
            )

        return HealthCheckResult(
            service="database",
            status=HealthStatus.DEGRADED,
            response_time_ms=0,
            message="No database configured (using SQLite fallback)",
        )

    except Exception as e:
        response_time = (time.time() - start_time) * 1000
        return HealthCheckResult(
            service="database",
            status=HealthStatus.UNHEALTHY,
            response_time_ms=response_time,
            message=str(e),
        )


def register_default_health_checks():
    health_checker.register_check("music_microservice", check_music_microservice)
    health_checker.register_check("database", check_database)

    for name in ["deezer", "vk"]:

        async def check_cb(name=name):
            cb = CircuitBreakerRegistry.get(name)
            if not cb:
                return HealthCheckResult(
                    service=f"circuit_breaker_{name}",
                    status=HealthStatus.UNKNOWN,
                    response_time_ms=0,
                    message="Circuit breaker not registered",
                )

            status = cb.get_status()
            if status["is_healthy"]:
                return HealthCheckResult(
                    service=f"circuit_breaker_{name}",
                    status=HealthStatus.HEALTHY,
                    response_time_ms=0,
                    message=f"State: {status['state']}, Failures: {status['failure_count']}",
                )

            return HealthCheckResult(
                service=f"circuit_breaker_{name}",
                status=HealthStatus.DEGRADED,
                response_time_ms=0,
                message=f"State: {status['state']}, Failures: {status['failure_count']}",
            )

        health_checker.register_check(f"circuit_breaker_{name}", check_cb)

    logger.info("Default health checks registered")
