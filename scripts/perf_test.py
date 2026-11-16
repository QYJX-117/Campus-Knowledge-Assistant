#!/usr/bin/env python3
"""Performance test: concurrent API stress test."""

import time
import threading
import requests
import sys

BASE = "http://localhost:8000/api"
EMAIL = "admin@campus.example"
PASSWORD = "admin123"

def get_token():
    r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    return r.json()["data"]["token"]

def single_chat(token, idx):
    start = time.time()
    try:
        r = requests.post(f"{BASE}/chat/sync", headers={"Authorization": f"Bearer {token}"},
                          json={"question": f"河海大学怎么样？#{idx}"}, timeout=30)
        elapsed = time.time() - start
        return elapsed, r.status_code
    except Exception as e:
        return time.time() - start, str(e)

def run_concurrent(n=10):
    print(f"Starting {n} concurrent chat requests...")
    token = get_token()
    threads = []
    results = []

    t0 = time.time()
    for i in range(n):
        t = threading.Thread(target=lambda: results.append(single_chat(token, len(results))))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    total_time = time.time() - t0
    latencies = [r[0] for r in results if isinstance(r[1], int) and r[1] == 200]
    failures = [r for r in results if r[1] != 200]

    print(f"\n=== Results ===")
    print(f"Total: {n} requests in {total_time:.1f}s")
    print(f"Success: {len(latencies)}, Failures: {len(failures)}")
    if latencies:
        latencies.sort()
        print(f"Latency (ms): min={latencies[0]*1000:.0f} avg={sum(latencies)/len(latencies)*1000:.0f} max={latencies[-1]*1000:.0f}")
        print(f"Throughput: {n/total_time:.1f} req/s")
    for f in failures:
        print(f"  FAIL: {f}")

if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run_concurrent(n)
