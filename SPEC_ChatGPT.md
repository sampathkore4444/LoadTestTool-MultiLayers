Alright—let’s build this **end-to-end on Ubuntu** in a way you can actually run and learn from. We’ll keep it practical and minimal, but still match your architecture:

👉 **Streamlit (controller) → wrk nodes → NGINX → Backend → OpenTelemetry → Jaeger**

---

# 🧱 Step 0 — Prerequisites

Install basics:

```bash
sudo apt update
sudo apt install docker.io docker-compose python3-pip -y
sudo usermod -aG docker $USER
```

Log out & back in (so Docker works without sudo)

---

# 🗂️ Step 1 — Create project structure

```bash
mkdir load-test-lab && cd load-test-lab
mkdir backend worker streamlit otel
```

---

# 🚀 Step 2 — Backend API (instrumented)

We’ll use Python + OpenTelemetry

### `backend/app.py`

```python
from flask import Flask
import time

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

span_processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://otel:4318/v1/traces")
)
trace.get_tracer_provider().add_span_processor(span_processor)

app = Flask(__name__)

@app.route("/api")
def api():
    with tracer.start_as_current_span("backend-work"):
        time.sleep(0.05)  # simulate work
        return {"message": "ok"}
```

### `backend/Dockerfile`

```dockerfile
FROM python:3.10
WORKDIR /app
COPY app.py .
RUN pip install flask opentelemetry-sdk opentelemetry-exporter-otlp
CMD ["python", "app.py"]
```

---

# 🌐 Step 3 — NGINX

### `nginx.conf`

```nginx
events {}

http {
  server {
    listen 80;

    location / {
      proxy_pass http://backend:5000;
    }
  }
}
```

---

# ⚙️ Step 4 — OpenTelemetry Collector

### `otel/otel-collector.yaml`

```yaml
receivers:
  otlp:
    protocols:
      http:

exporters:
  jaeger:
    endpoint: jaeger:14250
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      exporters: [jaeger]
```

---

# 🔥 Step 5 — wrk worker service

This is your “wrk node”

### `worker/worker.py`

```python
from flask import Flask, request, jsonify
import subprocess

app = Flask(__name__)

@app.route("/run", methods=["POST"])
def run():
    data = request.json

    cmd = [
        "wrk",
        f"-t{data['threads']}",
        f"-c{data['connections']}",
        f"-d{data['duration']}",
        "--latency",
        data['url']
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return jsonify({"output": result.stdout})
```

### `worker/Dockerfile`

```dockerfile
FROM python:3.10
RUN apt update && apt install -y wrk
WORKDIR /app
COPY worker.py .
RUN pip install flask
CMD ["python", "worker.py"]
```

---

# 🎛️ Step 6 — Streamlit controller

### `streamlit/app.py`

```python
import streamlit as st
import requests

st.title("Load Test Controller")

url = st.text_input("URL", "http://nginx/api")
threads = st.slider("Threads", 1, 8, 2)
connections = st.slider("Connections", 10, 500, 100)
duration = st.text_input("Duration", "10s")

workers = [
    "http://worker1:5000/run",
    "http://worker2:5000/run"
]

if st.button("Run Test"):
    results = []

    for w in workers:
        r = requests.post(w, json={
            "url": url,
            "threads": threads,
            "connections": connections,
            "duration": duration
        })
        results.append(r.json()["output"])

    for res in results:
        st.text(res)
```

### `streamlit/Dockerfile`

```dockerfile
FROM python:3.10
WORKDIR /app
COPY app.py .
RUN pip install streamlit requests
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

---

# 🐳 Step 7 — Docker Compose (everything together)

### `docker-compose.yml`

```yaml
version: "3"

services:
  backend:
    build: ./backend
    ports:
      - "5000:5000"

  nginx:
    image: nginx
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "8080:80"
    depends_on:
      - backend

  otel:
    image: otel/opentelemetry-collector
    volumes:
      - ./otel/otel-collector.yaml:/etc/otel/config.yaml
    command: ["--config=/etc/otel/config.yaml"]
    ports:
      - "4318:4318"

  jaeger:
    image: jaegertracing/all-in-one
    ports:
      - "16686:16686"

  worker1:
    build: ./worker

  worker2:
    build: ./worker

  streamlit:
    build: ./streamlit
    ports:
      - "8501:8501"
```

---

# ▶️ Step 8 — Run everything

```bash
docker-compose up --build
```

---

# 🌐 Step 9 — Access UI

* Streamlit:
  👉 [http://localhost:8501](http://localhost:8501)

* Jaeger (traces):
  👉 [http://localhost:16686](http://localhost:16686)

---

# 🧪 Step 10 — Run your first test

In Streamlit:

* URL: `http://nginx/api`
* Click **Run Test**

---

# 📊 What you’ll see

## In Streamlit

* wrk output (RPS, latency)

## In Jaeger

* trace per request:

```text
nginx → backend-work
```

---

# 🔥 What you just built

✔ Distributed load testing (2 wrk nodes)
✔ UI controller (Streamlit)
✔ Observability with OpenTelemetry
✔ Trace visualization in Jaeger

---

# ⚠️ Next improvements (optional)

* Add Kong between nginx and backend
* Add trace headers propagation
* Aggregate RPS across workers
* Add charts in Streamlit

---

# 🧠 Final takeaway

You now have:

```text
Load generation → wrk workers
Control → Streamlit
Tracing → OpenTelemetry
Visualization → Jaeger
```

---

If you want, next I can help you:
👉 add Kong + per-layer tracing (nginx vs kong vs backend breakdown)
👉 or scale to 5–10 wrk nodes like real production testing
