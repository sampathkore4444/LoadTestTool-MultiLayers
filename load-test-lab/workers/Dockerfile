FROM ubuntu:22.04
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    libssl-dev \
    git \
    lua5.3 \
    lua-socket \
    python3-pip \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /wrk2
RUN git clone https://github.com/giltene/wrk2.git . && make -j$(nproc) && cp wrk /usr/local/bin/wrk2
WORKDIR /app
COPY worker.py .
RUN pip3 install --no-cache-dir flask psycopg2-binary opentelemetry-sdk \
    opentelemetry-exporter-otlp opentelemetry-instrumentation-psycopg2
EXPOSE 5000
CMD ["python3", "worker.py"]
