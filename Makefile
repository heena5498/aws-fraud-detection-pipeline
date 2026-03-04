# Fraud Detection Pipeline - Quick Start Guide

.PHONY: help install setup data etl train api stream clean

help:
	@echo "Fraud Detection Pipeline Commands:"
	@echo ""
	@echo "  make install       - Install dependencies"
	@echo "  make setup         - Setup directories and download data"
	@echo "  make data          - Download/generate transaction data"
	@echo "  make etl           - Run full ETL pipeline (Bronze→Silver→Gold)"
	@echo "  make train         - Train fraud detection model"
	@echo "  make api           - Start FastAPI inference service"
	@echo "  make kafka         - Start Kafka infrastructure (Docker)"
	@echo "  make producer      - Stream synthetic transactions to Kafka"
	@echo "  make consumer      - Run real-time fraud detection consumer"
	@echo "  make drift         - Monitor model drift"
	@echo "  make notebook      - Start Jupyter notebook"
	@echo "  make clean         - Clean generated files"
	@echo "  make full-pipeline - Run complete pipeline from scratch"
	@echo ""

install:
	pip install -r requirements.txt
	@echo "✓ Dependencies installed"

setup: install
	@mkdir -p data/raw data/bronze data/silver data/gold data/alerts ml/models logs
	@echo "✓ Project structure created"

data:
	python scripts/download_data.py
	@echo "✓ Data ready"

etl:
	@echo "Running ETL pipeline..."
	python etl/bronze_layer.py
	python etl/silver_layer.py
	python etl/gold_layer.py
	@echo "✓ ETL complete"

train:
	python ml/train.py
	@echo "✓ Model trained"

api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

kafka:
	docker-compose up -d
	@echo "✓ Kafka started on localhost:9092"
	@echo "✓ Kafka UI available at http://localhost:8080"

kafka-stop:
	docker-compose down
	@echo "✓ Kafka stopped"

producer:
	python streaming/producer.py --rate 10 --duration 60

consumer:
	python streaming/consumer.py

drift:
	python ml/drift_monitor.py

notebook:
	jupyter notebook notebooks/eda.ipynb

test:
	pytest tests/ -v

clean:
	@echo "Cleaning generated files..."
	rm -rf data/bronze/*.parquet
	rm -rf data/silver/*.parquet
	rm -rf data/gold/*.parquet
	rm -rf ml/models/*.pkl
	rm -rf mlruns/
	rm -rf logs/*.log
	@echo "✓ Cleaned"

# Run complete pipeline from scratch
full-pipeline: setup data etl train
	@echo "=" 
	@echo "✓ Complete pipeline executed successfully!"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Start API:      make api"
	@echo "  2. Start Kafka:    make kafka"
	@echo "  3. Start producer: make producer"
	@echo "  4. Start consumer: make consumer"
	@echo ""

# Quick demo - run everything
demo: full-pipeline
	@echo "Starting demo..."
	@echo "1. Starting Kafka..."
	docker-compose up -d
	sleep 10
	@echo "2. Starting API (background)..."
	uvicorn api.main:app --host 0.0.0.0 --port 8000 &
	sleep 5
	@echo "3. Starting producer (background)..."
	python streaming/producer.py --rate 5 --duration 30 &
	sleep 2
	@echo "4. Starting consumer..."
	python streaming/consumer.py
