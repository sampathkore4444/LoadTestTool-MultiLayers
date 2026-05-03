from flask import Flask, request, jsonify
import subprocess
import json
import os
import threading
import time
import psycopg2
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from concurrent.futures import ThreadPoolExecutor, as_completed

app = Flask(__name__)

# Tracing
trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)
span_processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces")
)
trace.get_tracer_provider().add_span_processor(span_processor)

def parse_duration(s):
    s = str(s).strip()
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)

@app.route("/run", methods=["POST"])
def run():
    cfg = request.json
    cmd = [
        "wrk",
        "-t", str(cfg.get("threads", 4)),
        "-c", str(cfg.get("connections", 100)),
        "-d", cfg.get("duration", "10s"),
        "--latency",
        cfg["url"]
    ]
    rate = cfg.get("rate")
    if rate and rate > 0:
        cmd.insert(-1, "-R")
        cmd.insert(-1, str(rate))
    result = subprocess.run(cmd, capture_output=True, text=True)
    return jsonify({
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "config": cfg
    })

def db_worker_thread(db_cfg, query, duration_sec):
    conn = psycopg2.connect(**db_cfg)
    cur = conn.cursor()
    end = time.time() + duration_sec
    count = 0
    while time.time() < end:
        with tracer.start_as_current_span("db-query") as span:
            span.set_attribute("db.query", query)
            cur.execute(query)
            cur.fetchone()
        count += 1
    cur.close()
    conn.close()
    return count

@app.route("/run-db", methods=["POST"])
def run_db():
    cfg = request.json
    db_cfg = {
        "host": cfg.get("db_host", "database"),
        "dbname": cfg.get("db_name", "loadtest"),
        "user": cfg.get("db_user", "postgres"),
        "password": cfg.get("db_password", "postgres"),
    }
    query = cfg.get("query", "SELECT 1")
    duration = parse_duration(cfg.get("duration", "10s"))
    threads = cfg.get("threads", 4)

    with ThreadPoolExecutor(max_workers=threads) as ex:
        futures = [ex.submit(db_worker_thread, db_cfg, query, duration) for _ in range(threads)]
        total = sum(f.result() for f in as_completed(futures))

    return jsonify({
        "type": "db",
        "total_queries": total,
        "qps": round(total / duration, 2),
        "duration": duration
    })

@app.route("/health")
def health():
    return jsonify({"status": "ok", "worker": "wrk+db"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
