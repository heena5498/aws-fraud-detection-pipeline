#!/bin/bash
# Local Setup Script for Fraud Detection Pipeline

set -e  # Exit on error

echo "🚀 Setting up Fraud Detection Pipeline locally..."
echo ""

# Step 1: Create/activate virtual environment
echo "1️⃣ Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "   ✓ Created virtual environment"
else
    echo "   ✓ Virtual environment already exists"
fi

source .venv/bin/activate
echo "   ✓ Activated virtual environment"
echo ""

# Step 2: Install dependencies (with compatible versions for Python 3.14)
echo "2️⃣ Installing Python dependencies..."
.venv/bin/pip install --upgrade pip wheel setuptools
.venv/bin/pip install \
    pandas \
    numpy \
    pyarrow \
    boto3 \
    awswrangler \
    scikit-learn \
    xgboost \
    lightgbm \
    imbalanced-learn \
    mlflow \
    fastapi \
    uvicorn[standard] \
    pydantic \
    python-multipart \
    pandera \
    evidently \
    python-dotenv \
    pyyaml \
    requests \
    loguru \
    pytest \
    pytest-cov \
    black \
    flake8 \
    ipykernel \
    jupyter \
    notebook \
    kafka-python
echo "   ✓ Dependencies installed"
echo ""

# Step 3: Create directories
echo "3️⃣ Creating project directories..."
mkdir -p data/{raw,bronze,silver,gold,alerts}
mkdir -p ml/models
mkdir -p logs
echo "   ✓ Directories created"
echo ""

# Step 4: Set up .env file
echo "4️⃣ Setting up environment variables..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   ✓ Created .env file"
else
    echo "   ✓ .env file already exists"
fi
echo ""

echo "✨ Setup complete! Next steps:"
echo ""
echo "To activate the virtual environment:"
echo "  source .venv/bin/activate"
echo ""
echo "To start Kafka (in a separate terminal):"
echo "  docker-compose up -d"
echo "  # Kafka UI at http://localhost:8080"
echo ""
echo "To run the complete pipeline:"
echo "  source .venv/bin/activate"
echo "  python scripts/download_data.py        # Download dataset"
echo "  python etl/bronze_layer.py             # Run Bronze layer"
echo "  python etl/silver_layer.py             # Run Silver layer"  
echo "  python etl/gold_layer.py               # Run Gold layer"
echo "  python ml/train.py                     # Train ML model"
echo "  uvicorn api.main:app --reload          # Start API"
echo ""
