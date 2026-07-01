FROM python:3.10-slim

WORKDIR /app

# Install system dependencies if required (e.g. for building packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code and data
COPY . .

# Set environment variables for production (can be overridden by compose)
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8501

# Start both the webhook server and Streamlit app
CMD bash -c "python -m src.api.webhook.server & streamlit run src/ui/app.py --server.port 8501 --server.address 0.0.0.0"
