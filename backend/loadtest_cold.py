"""Замер без кэша: каждый запрос с новыми параметрами (маршрут, период, детализация).

    python backend/loadtest_cold.py [BASE_URL] [REQUESTS] [CONCURRENCY]

API требует вход: задайте TRAM_USER и TRAM_PASSWORD, скрипт получит сессию.
"""
import asyncio
import os
import random
import statistics
import sys
import time
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
C = int(sys.argv[3]) if len(sys.argv) > 3 else 64
ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50]
random.seed(int(os.getenv('SEED', '1')))


def url() -> str:
    start = date(2025, 11, 1) + timedelta(days=random.randrange(0, 50))
    end = start + timedelta(days=random.randrange(0, 10))
    route = random.choice(ROUTES)
    kind = random.choice(["forecast", "forecast", "forecast", "history"])
    if kind == "history":
        start, end = start - timedelta(days=120), end - timedelta(days=120)
    gran = random.choice(["day", "hour", "month"])
    return f"{BASE}/api/v1/{kind}?route={route}&start={start}&end={end}&granularity={gran}"


async def main() -> None:
    urls, lat, srv, bad = [url() for _ in range(N)], [], [], 0
    sem = asyncio.Semaphore(C)
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=C)) as client:
        if os.getenv('TRAM_USER'):
            login = await client.post(f"{BASE}/api/auth/login", json={"username": os.environ['TRAM_USER'], "password": os.environ['TRAM_PASSWORD']})
            login.raise_for_status()
        async def one(u: str) -> None:
            nonlocal bad
            async with sem:
                t = time.perf_counter()
                r = await client.get(u)
                lat.append((time.perf_counter() - t) * 1000)
                srv.append(float(r.headers.get('x-process-time-ms', 0)))
                bad += r.status_code != 200
        t0 = time.perf_counter()
        await asyncio.gather(*(one(u) for u in urls))
        wall = time.perf_counter() - t0
    q, sq = statistics.quantiles(lat, n=100), statistics.quantiles(srv, n=100)
    print(f"{len(set(urls))} уникальных URL из {N}: {N / wall:.0f} rps, p50 {q[49]:.0f} p95 {q[94]:.0f} p99 {q[98]:.0f} мс, не-200: {bad}; время обработки на сервере p50 {sq[49]:.1f} p95 {sq[94]:.1f} p99 {sq[98]:.1f} мс")


asyncio.run(main())
