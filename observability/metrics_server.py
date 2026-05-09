# metrics_server.py
import asyncio
import signal
from aiohttp import web
from prometheus_client import (
    Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
)

SEARCH_COUNT = Counter('app_searches_total', 'Total number of searches')
PLAY_COUNT = Counter('app_plays_total', 'Total number of plays')
ERROR_COUNT = Counter('app_errors_total', 'Total number of errors', ['type'])
QUEUE_SIZE = Gauge('app_queue_size', 'Current media queue size')
CACHE_HITS = Counter('app_cache_hits_total', 'Total cache hits')
WRAPPER_STATUS = Gauge(
    'app_wrapper_status',
    'Wrapper connectivity status (1=up, 0=down)'
)


class ObservabilityServer:
    def __init__(self, check_db, check_wrapper, check_vc):
        self.check_db = check_db
        self.check_wrapper = check_wrapper
        self.check_vc = check_vc
        self.runner = None

    async def health_handler(self, request):
        db_ok = await self.check_db()
        wrapper_ok = await self.check_wrapper()
        vc_ok = await self.check_vc()

        WRAPPER_STATUS.set(1 if wrapper_ok else 0)

        status = 200 if all([db_ok, wrapper_ok, vc_ok]) else 503
        return web.json_response({
            "status": "ok" if status == 200 else "error",
            "database": "up" if db_ok else "down",
            "wrapper": "up" if wrapper_ok else "down",
            "voice_client": "ready" if vc_ok else "error"
        }, status=status)

    async def metrics_handler(self, request):
        return web.Response(
            body=generate_latest(),
            content_type=CONTENT_TYPE_LATEST
        )

    async def start(self, port=8080):
        app = web.Application()
        app.router.add_get('/health', self.health_handler)
        app.router.add_get('/metrics', self.metrics_handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '0.0.0.0', port)
        await site.start()

    async def stop(self):
        if self.runner:
            await self.runner.cleanup()


async def shutdown(loop, signal_name, obs_server, log_listener):
    await obs_server.stop()
    log_listener.stop()

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    loop.stop()


def register_graceful_shutdown(loop, obs_server, log_listener):
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig, lambda s=sig: asyncio.create_task(
                shutdown(loop, s.name, obs_server, log_listener)
            )
        )
