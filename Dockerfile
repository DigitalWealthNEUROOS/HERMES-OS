# HERMES-OS Dockerfile
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    redis-server nginx curl wget git \
    build-essential cmake pkg-config \
    libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy all files
COPY . /app
WORKDIR /app

# Start script
COPY start-all.sh .
RUN chmod +x start-all.sh

# Expose all ports
EXPOSE 80 443 6379 8080 8090 9090 9091 9092 9093 9094 9095 9096 9097 9098

CMD ["bash", "start-all.sh"]
