#!/usr/bin/env python3
from flask import Flask, request, jsonify
import time
import random
import psycopg2
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor

# Tracing setup
resource = Resource.create({"service.name": "backend-api"})
trace.set_tracer_provider(TracerProvider(resource=resource))
tracer = trace.get_tracer(__name__)
span_processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://otel-collector:4318/v1/traces")
)
trace.get_tracer_provider().add_span_processor(span_processor)

app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)
Psycopg2Instrumentor().instrument()

def get_db():
    return psycopg2.connect(
        host="database", dbname="loadtest", user="postgres",
        password="postgres", connect_timeout=5
    )

@app.route("/api/hello")
def hello():
    with tracer.start_as_current_span("backend-api") as span:
        span.set_attribute("http.route", "/api/hello")
        with tracer.start_as_current_span("db-query"):
            try:
                conn = get_db()
                cur = conn.cursor()
                cur.execute("SELECT pg_sleep(0.01), id FROM requests LIMIT 1")
                cur.fetchone()
                cur.close()
                conn.close()
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("db.error", str(e))
        time.sleep(random.uniform(0.01, 0.05))
        return jsonify({"message": "ok", "node": "backend-1"})

@app.route("/api/users/<int:uid>")
def get_user(uid):
    with tracer.start_as_current_span("get-user"):
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT pg_sleep(0.005), %s", (uid,))
            cur.fetchone()
            cur.close()
            conn.close()
        except Exception as e:
            pass
        return jsonify({"uid": uid, "name": f"user-{uid}"})

@app.route("/api/db-ping")
def db_ping():
    with tracer.start_as_current_span("db-ping"):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
    return jsonify({"status": "db_ok"})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
