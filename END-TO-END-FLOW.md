# END-to-END-FLOW.md

KiloLoad – Production-Grade Distributed API Load Testing Platform
================================================================

1. Overview
-----------
KiloLoad is a production-grade, distributed load-testing platform designed to simulate real-world traffic across complex network architectures:

  Client → Edge Nginx → Kong Gateway → Backend Nginx → Backend API → Database

It combines high-performance load generation (wrk2/k6), chaos engineering, long-haul soak testing, and deep observability (OpenTelemetry, Prometheus, Grafana, Jaeger) to identify performance bottlenecks at every layer.

2. Architecture & High-Level Data Flow
--------------------------------------
The platform consists of three logical zones:

- Control Plane (UI & Orchestration)
- Data Plane (Load Generators / Workers)
- System Under Test (SUT) + Telemetry (Target environment + monitoring)

Request Lifecycle (User-triggered test)
- User configures test in Streamlit Controller (UI).
- Controller distributes job to Workers (HTTP POST /run or /run-db).
- Workers generate load against the target (via wrk2 for HTTP or raw SQL loops for DB).
- Traffic traverses: Edge Nginx → Kong → Backend Nginx → Backend API → Database.
- OpenTelemetry traces and Prometheus metrics are emitted throughout.
- Results flow back to Controller, which renders pass/fail, charts, and exports reports.

3. Component Deep Dive
-----------------------
3.1 Control Plane — Streamlit Controller
Location: load-test-lab/controller/
Role: Orchestration, configuration, visualization.
Tech: Python, Streamlit, Requests, Plotly.

Features:
- Target selector (5 routing options).
- Chaos toggle (enables fault injection during tests).
- SLO pass/fail engine (configurable latency/error thresholds).
- HTML report export and live Grafana/Jaiffer embeds.

Communication:
- Controller POSTs JSON to Workers (e.g. {threads, connections, duration, url, rate}).
- Parses wrk stdout, evaluates SLOs, and displays results.

3.2 Data Plane — Load Generators (Workers)
Location: load-test-lab/workers/
Role: Generate HTTP or database pressure.
Tech: wrk2 (C), Flask (Python), psycopg2.

Endpoints:
- POST /run
  - Spawns wrk2 subprocess with configured threads/connections/duration/rate.
  - Returns parsed wrk text output.
- POST /run-db
  - Spawns Python threads that loop SQL queries for the duration.
  - Returns QPS and total query count.

Tracing:
- Workers instrumented with OpenTelemetry.
- Each /run-db query emits a db-query span for separate DB-latency visibility in Jaeger.

3.3 System Under Test (SUT) Stack
Location: load-test-lab/{backend, kong, nginx, database}/

Component         | Image/Config            | Responsibility                        | Observability
------------------|-------------------------|---------------------------------------|------------------------------
Frontend Nginx    | nginx:alpine            | SSL termination, L7 routing           | stub_status (req/s)
Kong Gateway      | kong:3.4                | Auth, rate-limiting, plugins          | kong_http_status_count
Backend Nginx     | nginx:alpine            | Upstream proxy, keep-alive            | upstream_response_time
Backend API       | python:3.11 (or PHP)    | Business logic                        | backend-api span, db-query span
Database          | postgres:15 (or mysql)  | Persistence                           | pg_stat_statements via OTel
OTel Collector    | otel/opentelemetry-coll.| Receives traces, exports to Jaeger    | Port 4318

3.4 Observability Stack
Location: load-test-lab/{otel, prometheus, grafana, jaeger}/

- Jaeger: Trace waterfall visualization (per-hop latency).
- Prometheus: Time-series metrics (scrapes /metrics every 5s).
- Grafana: Dashboards for RPS, latency, error rate.
- Alertmanager: Fires alerts (error rate > 5%, p99 > 200ms, memory leaks).

4. Advanced Features
---------------------
4.1 Chaos Engineering (Phase 3)
Goal: Verify resilience under faults.
Component: chaos-agent (Go sidecar).

How it works:
- User toggles "Chaos" or Controller POSTs to http://chaos-agent:8081/inject.
- Payload example: {"type":"latency","target":"backend","value":"200ms","duration":"15s"}
- Agent uses tc/iptables to inject delay/drops.
- Timeline stored to /data/timeline.json.
Use case: Observe if Kong timeouts trigger when backend slows.

4.2 Soak Testing (Phase 3)
Goal: Detect memory leaks and long-tail regression.
Component: soak-monitor (Go service).

How it works:
- Runs for 1h/4h/24h.
- Polls Prometheus every 5m for RSS and p99 latency.
- Flags leaks (RSS growth > 50%) and regression (p99 > 2x baseline).

4.3 SLO & Reporting (Phase 4)
Goal: Gatekeeping for releases.

Logic:
- Parse wrk output for errors and compute error rate.
- Compare against user-defined SLOs (p95/p99 latency, error rate).
- Export HTML report with pass/fail status, charts, and trace links.

5. Frontend (Vue) ↔ Backend (API) Communication
------------------------------------------------
In your HRMS (PHP + Vue), KiloLoad can test in two ways:

Option A — Test via KiloLoad Workers (recommended)
- KiloLoad Worker acts as the "client" simulating Vue users.
- Worker → UAT Nginx/Kong → PHP API → MySQL.
- Advantage: Pure API stress without browser dependencies.

Option B — Real Vue App in browser
- Vue uses axios/fetch to call API: axios.get('/api/employees').
- KiloLoad cannot drive real browsers, but can simulate thousands of identical HTTP calls from workers to the same endpoints your Vue app calls.

Backend Processing Flow (for each request)
1. Nginx (front): Accept TCP, SSL handshake.
2. Kong: Auth/rate-limit. Returns 429 if exceeded; else proxies.
3. Backend Nginx: Buffering, keep-alive to PHP-FPM/uWSGI.
4. PHP Backend: Framework bootstrap, routing, DB query, JSON render.
5. MySQL: Query execution, returns rows.
6. Response travels back up to client/worker.

6. Operational Runbook
---------------------
A. Using Docker Compose (Full stack)
Prereq: Docker running.

Start:
  cd load-test-lab
  docker-compose up --build -d
  docker-compose ps              # verify healthy

Stop (graceful):
  docker-compose stop

Remove (keep volumes/data):
  docker-compose down

Remove all (including data):
  docker-compose down -v

B. Native / Local (Without Docker)
Prereqs: Python 3.11+, Java 17 (k6/Jaeger optional), Node, wrk2, Kong binary, DB installed.

Start DB (Postgres example):
  pg_ctl -D /usr/local/var/postgres start
  # or for MySQL
  sudo systemctl start mysql

Start Backend (Python example):
  cd backend
  export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
  pip install -r requirements.txt
  python app.py

Start Kong:
  kong start -c kong.conf

Start Backend Nginx:
  nginx -c backend-nginx/nginx.conf

Start Workers:
  cd workers
  pip install flask
  python worker.py

Start Controller (UI):
  cd controller
  pip install streamlit requests plotly
  streamlit run app.py
  # Open http://localhost:8501

Stop native services:
  Ctrl+C in each terminal or:
  kong stop
  nginx -s stop
  pg_ctl stop (or systemctl stop)

7. Access Points (Ports)
------------------------
Service            | URL                         | Purpose
-------------------|-----------------------------|----------------------------------
Controller UI      | http://localhost:8501       | Start tests, view results, SLO
Jaeger             | http://localhost:16686      | Trace waterfall viewer
Grafana            | http://localhost:3000       | Live metrics dashboards
Prometheus         | http://localhost:9090       | Metrics database/query
Kong Admin API     | http://localhost:8001       | Routes/plugins/consumers
Backend API        | http://localhost:8000       | Your application
Chaos Agent        | http://localhost:8081       | Fault injection API

8. Testing Your HRMS (PHP + Vue) — Practical Steps
--------------------------------------------------
1. Deploy your HRMS (PHP) and MySQL.
2. Ensure Kong points to your Backend Nginx/PHP upstream.
3. Optionally comment out the default Python backend in docker-compose.yml if testing only via workers.
4. Open Controller: http://localhost:8501
5. Choose Target (e.g., "Kong → Backend") and set URL to http://localhost:8000/api/employees.
6. Configure load: Threads, Connections, Duration.
7. Click Run.
8. Analyze:
   - Jaeger: locate slowest spans (Kong plugin vs DB query).
   - Grafana: watch RPS and latency during run.
   - SLO panel: pass/fail against your thresholds.

Outcome:
- If Kong bar is high → check auth plugin latency.
- If DB bar is high → optimize queries/indexes.
- If Backend bar is high → profile PHP code and DB calls.

9. Notes
--------
- Workers support both HTTP (wrk2) and direct DB (raw SQL) modes.
- Chaos agent is privileged and requires docker socket mount.
- SLO evaluation parses wrk stdout; for production precision, export detailed metrics from your PHP app with OpenTelemetry PHP instrumentation.
- Always restrict ALLOWED_TARGETS_REGEX and MAX_GLOBAL_RPS in production to prevent accidental external overload.
