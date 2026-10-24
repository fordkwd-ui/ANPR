"""High-throughput edge ingestion load testing tool.

Simulates gate-box edge traffic (e.g. 5 events/sec for 10 minutes)
and validates that p95 response latency remains strictly under 300 ms locally.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import math
import random
import time
import uuid
import httpx

SAMPLE_PLATES = [
    "DL01AB1234",
    "KA05M5678",
    "MH12CD9999",
    "UP16EF4321",
    "22BH1234AA",
    "24BH9876BB",
    "HR26DQ5555",
    "WB02K7777",
]

VEHICLE_TYPES = ["truck", "car", "van", "pickup", "bus"]
LOAD_TYPES = ["timber_logs", "sand", "stone_gravel", "empty", "bags", "covered"]


def percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = (len(sorted_data) - 1) * (p / 100.0)
    floor_idx = math.floor(idx)
    ceil_idx = math.ceil(idx)
    if floor_idx == ceil_idx:
        return sorted_data[int(idx)]
    d0 = sorted_data[int(floor_idx)] * (ceil_idx - idx)
    d1 = sorted_data[int(ceil_idx)] * (idx - floor_idx)
    return d0 + d1


async def send_single_event(
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    latencies: list[float],
) -> bool:
    event_uid = f"load-test-{uuid.uuid4()}"
    plate = random.choice(SAMPLE_PLATES)
    payload = {
        "event_uid": event_uid,
        "camera_id": "cam-a-anpr",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "plate_raw": plate,
        "plate_conf": round(random.uniform(0.85, 0.99), 2),
        "vehicle_type": random.choice(VEHICLE_TYPES),
        "vehicle_color": random.choice(["white", "silver", "blue", "black"]),
        "load_type": random.choice(LOAD_TYPES),
        "load_conf": round(random.uniform(0.65, 0.95), 2),
    }

    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{base_url.rstrip('/')}/api/v1/events",
            json=payload,
            headers={"X-API-Key": api_key},
            timeout=5.0,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)
        return resp.status_code == 200
    except Exception as e:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(elapsed_ms)
        return False


async def run_load_test(base_url: str, api_key: str, rate: int, duration_seconds: int) -> None:
    print("=" * 60)
    print("🚀 STARTING ANPR CLOUD INGESTION LOAD TEST")
    print(f"   Target URL: {base_url}")
    print(f"   Rate:       {rate} events / second")
    print(f"   Duration:   {duration_seconds} seconds ({duration_seconds/60:.1f} minutes)")
    print(f"   Total:      ~{rate * duration_seconds} requests")
    print("=" * 60)

    latencies: list[float] = []
    success_count = 0
    failure_count = 0

    limits = httpx.Limits(max_connections=50, max_keepalive_connections=20)
    async with httpx.AsyncClient(limits=limits) as client:
        start_time = time.monotonic()
        total_intervals = duration_seconds

        for sec in range(total_intervals):
            batch_start = time.monotonic()

            tasks = [
                send_single_event(client, base_url, api_key, latencies)
                for _ in range(rate)
            ]
            results = await asyncio.gather(*tasks)

            for ok in results:
                if ok:
                    success_count += 1
                else:
                    failure_count += 1

            if (sec + 1) % 10 == 0 or sec == 0:
                current_p50 = percentile(latencies, 50)
                current_p95 = percentile(latencies, 95)
                print(
                    f"[{sec + 1:4d}s / {duration_seconds}s] "
                    f"Sent: {success_count + failure_count:5d} | "
                    f"Success: {success_count} | Fail: {failure_count} | "
                    f"p50: {current_p50:.1f}ms | p95: {current_p95:.1f}ms"
                )

            # Sleep remaining time to preserve exact 1-second interval
            batch_elapsed = time.monotonic() - batch_start
            sleep_time = max(0.0, 1.0 - batch_elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    total_time = time.monotonic() - start_time
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    max_lat = max(latencies) if latencies else 0.0

    print("=" * 60)
    print("📊 LOAD TEST RESULTS:")
    print(f"   Total Requests:     {len(latencies)}")
    print(f"   Successful:         {success_count}")
    print(f"   Failed:             {failure_count}")
    print(f"   Total Elapsed:      {total_time:.2f} s")
    print(f"   Actual Throughput:  {len(latencies)/total_time:.2f} req/s")
    print("-" * 60)
    print(f"   p50 Latency:        {p50:.2f} ms")
    print(f"   p95 Latency:        {p95:.2f} ms (Target: < 300 ms)")
    print(f"   p99 Latency:        {p99:.2f} ms")
    print(f"   Max Latency:        {max_lat:.2f} ms")
    print("=" * 60)

    if p95 < 300.0:
        print("✅ PERFORMANCE PASSED: p95 latency is strictly under 300 ms locally.")
    else:
        print("❌ PERFORMANCE WARNING: p95 latency exceeded 300 ms.")


def main():
    parser = argparse.ArgumentParser(description="ANPR Cloud Backend Load Tester")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of backend")
    parser.add_argument("--api-key", default="gate-edge-api-key-test", help="Device X-API-Key")
    parser.add_argument("--rate", type=int, default=5, help="Events per second (default: 5)")
    parser.add_argument(
        "--duration",
        type=int,
        default=600,
        help="Test duration in seconds (default: 600 s = 10 min)",
    )
    args = parser.parse_args()

    asyncio.run(run_load_test(args.url, args.api_key, args.rate, args.duration))


if __name__ == "__main__":
    main()
