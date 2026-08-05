FROM python:3.11-slim

WORKDIR /app

# Install system dependencies. gcc is needed because psutil==5.9.6 has no
# prebuilt aarch64/cp311 wheel, so pip falls back to compiling it from
# source on that platform (this was never caught before this image's
# first-ever CI build - the multi-arch build had never actually run).
RUN apt-get update && apt-get install -y \
    wireguard-tools \
    iproute2 \
    iputils-ping \
    openvpn \
    strongswan \
    qrencode \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p /config/wireguard /config/openvpn /config/ikev2

# Expose port
EXPOSE 5000

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000", "--reload"]
