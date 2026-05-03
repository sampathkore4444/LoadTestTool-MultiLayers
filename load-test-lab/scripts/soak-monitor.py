#!/usr/bin/env python3
"""
Soak test monitor - detects regressions and auto-stops tests
"""
import requests
import time
import sys
import os

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
REGRESSION_THRESHOLD = float(os.getenv("REGRESSION_THRESHOLD", "0.2"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

def get_metric(query):
    try:
        resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}, timeout=10)
        if resp.json().get("status") == "success" and resp.json()["data"]["result"]:
            return float(resp.json()["data"]["result"][0]["value"][1])
    except:
        pass
    return None

def check_regression():
    baseline_p95 = get_metric("histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))")
    current_p95 = get_metric("histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))")
    if baseline_p95 and current_p95:
        degradation = (current_p95 - baseline_p95) / baseline_p95 if baseline_p95 > 0 else 0
        if degradation > REGRESSION_THRESHOLD:
            return f"Latency regression detected: {degradation*100:.1f}% degradation"
    return None

def check_memory_leak():
    current_mem = get_metric("process_resident_memory_bytes")
    if current_mem and current_mem > 100 * 1024 * 1024:
        rate = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={
            "query": "rate(process_resident_memory_bytes[5m])"
        }, timeout=5).json()
        if rate.get("status") == "success" and rate["data"]["result"]:
            mem_rate = float(rate["data"]["result"][0]["value"][1])
            if mem_rate > 0:
                return f"Memory leak suspected: growing at {mem_rate/1024:.1f} KB/s"
    return None

def main():
    print(f"Soak monitor started (interval: {CHECK_INTERVAL}s)")
    while True:
        try:
            reg = check_regression()
            if reg:
                print(f"REGRESSION: {reg}")
                sys.exit(1)
            leak = check_memory_leak()
            if leak:
                print(f"WARNING: {leak}")
            time.sleep(CHECK_INTERVAL)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()