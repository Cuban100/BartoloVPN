FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wireguard-tools \
    iproute2 \
    iputils-ping \
    qrencode \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /config/wireguard

# Expose port (not 8080 - the linuxserver/wireguard image's built-in
# CoreDNS already binds 8080 in the shared network namespace this
# container runs in)
EXPOSE 8912

# Run the application
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8912"]
