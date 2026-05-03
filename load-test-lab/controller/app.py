import streamlit as st
import requests
import time
import json
import pandas as pd
import plotly.graph_objects as go
import urllib.request
from datetime import datetime

st.set_page_config(page_title="KiloLoad", layout="wide")
st.title("⚡ KiloLoad — API Load Tester")

# Target selector
target = st.selectbox("Target", [
    "Frontend nginx → Kong → Backend",
    "Kong → Backend",
    "Backend only",
    "Backend → Database (via API)",
    "Database only (raw query)"
])

url_map = {
    "Frontend nginx → Kong → Backend": "http://localhost/api/hello",
    "Kong → Backend": "http://localhost:8000/api/hello",
    "Backend only": "http://backend:5000/api/hello",
    "Backend → Database (via API)": "http://backend:5000/api/db-ping"
}
url = url_map.get(target, "")

col1, col2, col3 = st.columns(3)
with col1:
    workers_num = st.number_input("Worker nodes", 1, 10, 2, key="workers_num")
    threads = st.slider("Threads per worker", 1, 16, 4)
with col2:
    connections = st.slider("Connections per worker", 10, 500, 100)
    duration = st.text_input("Duration", "30s")
with col3:
    rate_limit = st.number_input("Rate (req/s, 0=unlimited)", 0, 100000, 0)

scenarios = ["Simple GET", "Mixed endpoints", "Auth + Rate limit", "Soak (5m)", "Spike (ramp 0→2k)", "Chaos (restart worker mid-test)"]
scenario = st.selectbox("Scenario", scenarios)

use_db_mode = "Database only" in target

if st.button("🚀 Run Test", type="primary"):
    workers = [f"http://worker{i+1}:5000/run" for i in range(workers_num)]
    progress = st.progress(0)
    results = []
    start_ts = time.time()
    for i, w in enumerate(workers):
        if use_db_mode:
            payload = {
                "threads": threads,
                "connections": 1,
                "duration": duration,
                "query": "SELECT 1",
                "db_host": "database",
                "db_name": "loadtest",
                "db_user": "postgres",
                "db_password": "postgres"
            }
            endpoint = f"http://worker{i+1}:5000/run-db"
        else:
            payload = {
                "threads": threads,
                "connections": connections,
                "duration": duration,
                "url": url,
                "rate": rate_limit if rate_limit else 0
            }
            endpoint = f"http://worker{i+1}:5000/run"
        try:
            r = requests.post(endpoint, json=payload, timeout=400)
            results.append(r.json())
            st.info(f"Worker {i+1}: completed")
        except Exception as e:
            results.append({"error": str(e)})
            st.error(f"Worker {i+1}: {str(e)}")
        progress.progress((i+1)/len(workers))
    elapsed = time.time() - start_ts
    st.success(f"Test finished in {elapsed:.1f}s")
    st.subheader("Results")
    for i, res in enumerate(results):
        st.text_area(f"Worker {i+1}", res.get("stdout", res.get("error", "N/A")), height=200)

# ===========================================
# Per-layer span viewer (OpenTelemetry)
# ===========================================
st.subheader("🕸️ Per-Layer Traces (OpenTelemetry)")
try:
    trace_url = "http://localhost:16686/api/traces?service=backend&limit=10&lookback=1m"
    with urllib.request.urlopen(trace_url, timeout=10) as resp:
        data = json.loads(resp.read())
    traces = data.get("data", [])
    if not traces:
        st.info("No traces found — generate some traffic first.")
    else:
        for t in traces:
            trace_id = t.get("traceID", "?")
            st.markdown(f"**Trace ID**: `{trace_id}`")
            spans = sorted(t.get("spans", []), key=lambda s: s.get("startTime", 0))
            # Build parent-child tree
            by_pid = {}
            for s in spans:
                pid = s.get("parentSpanID", "0")
                by_pid.setdefault(pid, []).append(s)
            def render_tree(span, depth=0):
                name = span.get("operationName", "?")
                dur = span.get("duration", 0) / 1e6  # µs → ms
                extra = ""
                for tag in span.get("tags", []):
                    if tag.get("key") == "http.status_code":
                        extra += f" status={tag.get('value')}"
                    if tag.get("key") == "db.statement":
                        extra += " [db]"
                st.markdown("%s%s **%s** — %.2f ms%s" % ("  "*depth, "└─" if depth else "", name, dur, extra))
                kids = by_pid.get(span.get("spanID", ""), [])
                for k in sorted(kids, key=lambda x: x.get("startTime", 0)):
                    render_tree(k, depth+1)
            root_spans = by_pid.get("0", [])
            for rs in sorted(root_spans, key=lambda x: x.get("startTime", 0)):
                render_tree(rs)
            st.markdown("---")
except Exception as e:
    st.warning(f"Could not fetch traces from Jaeger: {e}")

# Latency distribution (from recent traces)
try:
    trace_url = "http://localhost:16686/api/traces?service=backend&limit=30&lookback=5m"
    with urllib.request.urlopen(trace_url, timeout=10) as resp:
        data = json.loads(resp.read())
    traces = data.get("data", [])
    layers = {"backend-api": [], "db-query": []}
    for t in traces:
        for s in t.get("spans", []):
            name = s.get("operationName", "")
            dur_ms = s.get("duration", 0) / 1e6
            if name == "backend-api":
                layers["backend-api"].append(dur_ms)
            elif name == "db-query":
                layers["db-query"].append(dur_ms)
    if any(layers.values()):
        st.subheader("⏱️ Layer latency distribution")
        fig = go.Figure()
        for lyr, vals in layers.items():
            if vals:
                fig.add_trace(go.Box(y=vals, name=lyr, boxmean="sd"))
        fig.update_layout(title="Per-span duration (ms)", yaxis_title="ms")
        st.plotly_chart(fig, use_container_width=True)
except Exception:
    pass

# Real-time Prometheus metrics
try:
    pm = requests.get("http://localhost:9090/api/v1/query", params={"query": "rate(kong_http_status_count[1m])"}, timeout=10).json()
    if pm.get("status") == "success":
        st.subheader("📈 Live Prometheus metrics")
        vals = pm["data"]["result"]
        for v in vals[:5]:
            lbl = v["metric"].get("__name__", "?")
            val = float(v["value"][1]) if len(v["value"]) > 1 else 0
            st.metric(label=lbl, value=f"{val:.1f}/s")
except Exception:
    pass

st.subheader("Quick Stats")
st.code("""
# Metrics available at:
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000
# Jaeger:     http://localhost:16686
# Kong Admin: http://localhost:8001
""")
