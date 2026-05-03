SHELL := /bin/bash

.PHONY: up build down logs test clean

up:
	docker-compose up -d

build:
	docker-compose up --build -d

down:
	docker-compose down

logs:
	docker-compose logs -f

test: up
	@echo "Run tests at http://localhost:8501"
	@sleep 15 && open http://localhost:8501 || echo "Open http://localhost:8501 manually"

clean: down
	rm -rf .pytest_cache .coverage htmlcov

chaos:
	docker-compose stop worker1
	@echo "Chaos: stopped worker1; run tests to observe partial failure"

soak:
	@echo "Running 5-min soak test..."
	curl -X POST http://worker1:5000/run -H "Content-Type: application/json" -d '{"threads":4,"connections":50,"duration":"300s","url":"http://localhost/api/hello","rate":0}'
