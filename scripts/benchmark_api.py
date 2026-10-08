"""
API Load Test
=============
Measures /predict latency (p50/p95/p99) and throughput under concurrent load.

Usage:
    uvicorn api.main:app --port 8000 --workers 4    # in another terminal
    python scripts/benchmark_api.py --requests 2000 --concurrency 20
"""

import argparse
import asyncio
import random
import time
from datetime import datetime, timedelta

import httpx
import numpy as np


def random_transaction(i: int) -> dict:
    """Build a realistic /predict request body."""
    ts = datetime.now() - timedelta(minutes=random.randint(0, 60 * 24 * 7))
    return {
        "transaction_id": f"bench_{i}",
        "user_id": f"user_{random.randint(1, 10000)}",
        "merchant_id": f"merchant_{random.randint(1, 5000)}",
        "amount": round(float(np.random.lognormal(mean=4, sigma=1.5)), 2),
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "merchant_category": random.choice(["retail", "grocery", "restaurant", "online", "travel"]),
        "country": random.choice(["US", "UK", "CA", "FR", "DE"]),
    }


async def run(url: str, total: int, concurrency: int, warmup: int):
    latencies, errors = [], 0
    queue = asyncio.Queue()
    for i in range(total):
        queue.put_nowait(i)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Warm-up requests are not measured (first calls pay one-off costs)
        for i in range(warmup):
            await client.post(url, json=random_transaction(-i))

        async def worker():
            nonlocal errors
            while not queue.empty():
                i = queue.get_nowait()
                body = random_transaction(i)
                start = time.perf_counter()
                try:
                    resp = await client.post(url, json=body)
                    if resp.status_code != 200:
                        errors += 1
                        continue
                except httpx.HTTPError:
                    errors += 1
                    continue
                latencies.append((time.perf_counter() - start) * 1000)

        start = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - start

    lat = np.array(latencies)
    print("=" * 50)
    print(f"Requests:     {total:,} ({concurrency} concurrent)")
    print(f"Succeeded:    {len(lat):,}   Errors: {errors}")
    print(f"Throughput:   {len(lat) / elapsed:,.1f} requests/sec")
    if len(lat):
        print(f"Latency p50:  {np.percentile(lat, 50):.1f} ms")
        print(f"Latency p95:  {np.percentile(lat, 95):.1f} ms")
        print(f"Latency p99:  {np.percentile(lat, 99):.1f} ms")
        print(f"Latency max:  {lat.max():.1f} ms")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Load test the fraud scoring API")
    parser.add_argument("--url", default="http://localhost:8000/predict")
    parser.add_argument("--requests", type=int, default=2000)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=20)
    args = parser.parse_args()

    asyncio.run(run(args.url, args.requests, args.concurrency, args.warmup))


if __name__ == "__main__":
    main()
