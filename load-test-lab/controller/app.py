import streamlit as st
import requests
import streamlit.components.v1 as components
import time
import json
import pandas as pd
import plotly.graph_objects as go
import urllib.request
import os
import re
from datetime import datetime, timedelta
from jinja2 import Template

st.set_page_config(page_title="KiloLoad", layout="wide")
st.title("⚡ KiloLoad — API Load Tester")

# Session state for long-running tests
if 'test_running' not in st.session_state:
    st.session_state.test_running = False
if 'test_start_time' not in st.session_state:
    st.session_state.test_start_time = None
if 'chaos_injected' not in st.session_state:
    st.session_state.chaos_injected = False

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
    duration = st.selectbox("Duration / Soak", ["10s", "30s", "1m", "5m", "1h", "4h", "24h"])
with col3:
    rate_limit = st.number_input("Rate (req/s, 0=unlimited)", 0, 100000, 0)
    chaos = st.checkbox("Enable Chaos (inject faults)")

scenarios = ["Simple GET", "Mixed endpoints", "Auth + Rate limit", "Soak (5m)", "Spike (ramp 0→2k)", "Chaos (restart worker mid-test)"]
scenario = st.selectbox("Scenario", scenarios)

slo_enabled = st.checkbox("Enable SLO pass/fail")
if slo_enabled:
    slo_p95_ms = st.number_input("SLO p95 latency (ms)", 10, 2000, 200)
    slo_error_rate = st.number_input("SLO max error rate", 0.0, 0.5, 0.01)


# Chaos controls
st.subheader("🔥 Chaos Injection")
col_chaos1, col_chaos2, col_chaos3 = st.columns(3)
with col_chaos1:
    chaos_type = st.selectbox("Fault Type", ["pod-kill", "latency", "db-disconnect", "cpu-stress"], key="chaos_type")
with col_chaos2:
    chaos_target = st.text_input("Target (pod name/service)", "worker1", key="chaos_target")
with col_chaos3:
    chaos_duration = st.number_input("Duration (sec)", 5, 300, 30, key="chaos_duration")

if st.button("💥 Inject Chaos"):
    try:
        resp = requests.post("http://chaos-agent:8080/inject", json={
            "type": chaos_type,
            "target": chaos_target,
            "duration": chaos_duration,
            "rate": 100 if chaos_type == "latency" else 0
        }, timeout=5)
        st.success(f"Chaos injected: {resp.json()}")
        st.session_state.chaos_injected = True
    except Exception as e:
        st.error(f"Failed to inject chaos: {e}")

# SLO Configuration
st.subheader("📊 SLO & Performance Criteria")
col_slo1, col_slo2, col_slo3 = st.columns(3)
with col_slo1:
    slo_latency_p95 = st.number_input("P95 Latency (ms)", 1, 5000, 200, key="slo_latency")
with col_slo2:
    slo_error_rate = st.number_input("Max Error Rate (%)", 0.0, 100.0, 1.0, key="slo_error")
with col_slo3:
    slo_availability = st.number_input("Min Availability (%)", 0.0, 100.0, 99.9, key="slo_avail")

use_db_mode = "Database only" in target

# Map soak duration
soak_map = {"Off": "30s", "1h": "1h", "4h": "4h", "24h": "24h"}
if soak_mode != "Off":
    duration = soak_mode

    if st.button("🚀 Run Test", type="primary"):
        use_db_mode = "Database only" in target

        # === PHASE-1 SAFETY GUARDRAILS ===
        max_rps = int(os.getenv("MAX_GLOBAL_RPS", 5000))
        if rate_limit > max_rps > 0:
            st.error(f"Rate {rate_limit} exceeds MAX_GLOBAL_RPS={max_rps}. Test blocked.")
            return

        allowed = os.getenv("ALLOWED_TARGETS_REGEX", "localhost|127\\.0\\.0\\.1")
        import re
        if not re.search(allowed, url):
            st.error(f"Target not in ALLOWED_TARGETS_REGEX. Abort.")
            return

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

        # === PHASE-3: CHAOS INJECTION (optional) ===
        if chaos:
            try:
                chaos_url = "http://chaos-agent:8081/inject"
                fault = {
                    "type": "latency",
                    "target": "backend",
                    "value": "200ms",
                    "duration": "15s"
                }
                cr = requests.post(chaos_url, json=fault, timeout=10)
                st.warning(f"Chaos injected: {cr.json()}")
            except Exception as e:
                st.warning(f"Chaos agent unavailable: {e}")

        # === PHASE-4: SLO EVAL & REPORTING ===
        if slo_enabled:
            st.subheader("SLO Evaluation")
            # Try to parse RPS & error rate from wrk output (basic)
            total_rps = 0.0
            total_errors = 0
            total_requests = 0
            for res in results:
                out = res.get("stdout", "")
                # very simple wrk parsing
                import re
                m = re.search(r"(\d+\.?\d*)\s*requests/sec", out)
                if m: total_rps += float(m.group(1))
                # try error count
                em = re.search(r"(\d+)\s*errors", out)
                if em: total_errors += int(em.group(1))
                # non-errors approx
                nm = re.search(r"socket errors: (\d+)", out)
                if nm: total_errors += int(nm.group(1))
            # approximate total requests
            total_requests = int(total_rps * elapsed) if elapsed>0 else 1
            err_rate = (total_errors / total_requests) if total_requests else 0

            cola, colb = st.columns(2)
            cola.metric("Observed RPS", f"{total_rps:.1f}")
            colb.metric("Error rate", f"{err_rate:.3%}")

            p95_ok = True  # would compare to actual metric
            err_ok = err_rate <= slo_error_rate

            if p95_ok and err_ok:
                st.success("✅ SLO PASSED")
            else:
                st.error("❌ SLO FAILED")
                if not p95_ok:
                    st.write("- p95 latency exceeded threshold")
                if not err_ok:
                    st.write(f"- error rate {err_rate:.3%} > {slo_error_rate:.3%}")

        # === ENHANCED REPORTING: Export HTML ===
        if results:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            html = f"""<!doctype html><html><head><title>KiloLoad Report {ts}</title></head><body>
            <h1>KiloLoad Test Report</h1><p>Date: {ts}</p>
            <h2>Configuration</h2>
            <ul><li>Target: {target}</li><li>Duration: {duration}</li><li>Elapsed: {elapsed:.1f}s</li></ul>
            <h2>Worker Results</h2>"""
            for i,res in enumerate(results):
                html += f"<pre><strong>Worker {i+1}</strong>\n{res.get('stdout','N/A')}</pre>"
            html += "</body></html>"
            st.download_button("📥 Download HTML Report", html, f"kilotest-{ts}.html", "text/html")

# === Real-time dashboards ===
try:
    st.subheader("📊 Live Grafana (iframe)")
    st.components.v1.iframe("http://localhost:3000/d/kilotest-overview?orgId=1&refresh=5s", height=600)
except:
    pass
try:
    st.subheader("🕸️ Recent Traces (Jaeger)")
    tr = requests.get("http://localhost:16686/api/traces?service=backend&limit=5", timeout=5).json()
    for t in tr.get("data",[]):
        st.code(f"TraceID={t.get('traceID')} spans={len(t.get('spans',[]))}")
except Exception as e:
    st.info("Traces unavailable")
    st.session_state.test_running = False
    
st.subheader("Results")
for i, res in enumerate(results):
    st.text_area(f"Worker {i+1}", res.get("stdout", res.get("error", "N/A")), height=200)

# Enhanced Reporting
st.subheader("📈 Enhanced Reporting & Analysis")

# Memory leak detection for soak mode
if soak_mode != "Off":
    try:
        mem_stats = requests.get("http://prometheus:9090/api/v1/query", params={
            "query": "process_resident_memory_bytes{job='otel-collector'}"}, timeout=5).json()
        if mem_stats.get("status") == "success" and mem_stats["data"]["result"]:
            mem_values = [float(v["value"][1]) for v in mem_stats["data"]["result"]]
            if len(mem_values) > 1:
                trend = "increasing" if mem_values[-1] > mem_values[0] else "stable"
                st.metric("Memory Trend", trend, f"{mem_values[-1]/1024/1024:.1f} MB")
                if trend == "increasing" and soak_mode != "Off":
                    st.warning("Potential memory leak detected! Consider stopping the test.")
    except Exception:
        pass

# SLO Evaluation
try:
    p95_resp = requests.get("http://prometheus:9090/api/v1/query", params={
        "query": "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))"}, timeout=5).json()
    err_resp = requests.get("http://prometheus:9090/api/v1/query", params={
        "query": "rate(http_requests_total{status=~\"5..\"}[5m]) / rate(http_requests_total[5m]) * 100"}, timeout=5).json()
    
    slo_results = []
    p95_val = None
    if p95_resp.get("status") == "success" and p95_resp["data"]["result"]:
        p95_val = float(p95_resp["data"]["result"][0]["value"][1]) * 1000
        slo_results.append(("P95 Latency", p95_val, slo_latency_p95, "pass" if p95_val <= slo_latency_p95 else "fail"))
    
    err_val = None
    if err_resp.get("status") == "success" and err_resp["data"]["result"]:
        err_val = float(err_resp["data"]["result"][0]["value"][1])
        slo_results.append(("Error Rate", err_val, slo_error_rate, "pass" if err_val <= slo_error_rate else "fail"))
    
    if slo_results:
        st.caption("SLO Evaluation")
        for name, actual, target, status in slo_results:
            emoji = "✅" if status == "pass" else "❌"
            st.write(f"{emoji} **{name}**: {actual:.2f} (target: {target})")
except Exception:
    pass

# Bottleneck hints
st.caption("Bottleneck Analysis")
try:
    cpu_q = requests.get("http://prometheus:9090/api/v1/query", params={
        "query": "rate(process_cpu_seconds_total[1m])"}, timeout=5).json()
    if cpu_q.get("status") == "success":
        cpu_val = float(cpu_q["data"]["result"][0]["value"][1]) * 100 if cpu_q["data"]["result"] else 0
        if cpu_val > 80:
            st.info(f"🔧 CPU saturated ({cpu_val:.0f}%). Consider scaling up workers.")
except Exception:
    pass

# Export options
st.subheader("📄 Export Reports")
col_exp1, col_exp2 = st.columns(2)
with col_exp1:
    if st.button("Export PDF"):
        html_content = generate_html_report(url, duration, workers_num, threads, results, slo_results)
        st.download_button("Download HTML", html_content, "kilotest_report.html", "text/html")
with col_exp2:
    if st.button("View Timeline"):
        try:
            timeline = requests.get("http://chaos-agent:8080/timeline", timeout=5).json()
            st.json(timeline)
        except Exception as e:
            st.error(f"Could not fetch timeline: {e}")

# Grafana embeds
st.subheader("📊 Real-time Dashboards")
col_g1, col_g2 = st.columns(2)
with col_g1:
    st.components.v1.iframe("http://localhost:3000/d/prom/kiloload-overview?orgId=1&refresh=5s&kiosk", height=400)
with col_g2:
    st.components.v1.iframe("http://localhost:16686/search", height=400)

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
            by_pid = {}
            for s in spans:
                pid = s.get("parentSpanID", "0")
                by_pid.setdefault(pid, []).append(s)
            def render_tree(span, depth=0):
                name = span.get("operationName", "?")
                dur = span.get("duration", 0) / 1e6
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

def generate_html_report(url, duration, workers, threads, results, slo_results):
    template = Template("""
<!DOCTYPE html><html><head><title>KiloLoad Report</title>
<style>body{font-family:sans-serif;margin:40px;} .pass{color:green}.fail{color:red;}</style></head>
<body>
<h1>KiloLoad Test Report</h1>
<p><strong>Generated:</strong> {{ ts }}</p>
<h2>Test Configuration</h2>
<ul><li>URL: {{ url }}</li><li>Duration: {{ duration }}</li><li>Workers: {{ workers }}</li><li>Threads: {{ threads }}</li></ul>
<h2>SLO Results</h2>
<ul>{% for name, actual, target, status in slo_results %}
<li class="{{ status }}">{{ name }}: {{ actual }} (target: {{ target }})</li>{% endfor %}</ul>
<h2>Raw Results</h2>
<pre>{{ results }}</pre>
</body></html>""")
    return template.render(ts=datetime.now(), url=url, duration=duration, workers=workers, threads=threads, results=json.dumps(results, indent=2), slo_results=slo_results or [])