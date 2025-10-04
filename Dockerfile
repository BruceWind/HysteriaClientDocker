# Use Python base image with curl and ca-certificates
FROM python:3.11-alpine

# Install necessary packages
RUN apk add --no-cache curl ca-certificates

# Create hysteria directory
RUN mkdir -p /etc/hysteria

# Set working directory 
WORKDIR /app

# Download Hysteria binary (latest version)
# Auto-detect CPU architecture and download appropriate binary
RUN ARCH=$(uname -m) && \
    case $ARCH in \
        x86_64) HYSTERIA_ARCH="amd64" ;; \
        aarch64) HYSTERIA_ARCH="arm64" ;; \
        armv7l) HYSTERIA_ARCH="armv7" ;; \
        i386) HYSTERIA_ARCH="386" ;; \
        *) echo "Unsupported architecture: $ARCH" && exit 1 ;; \
    esac && \
    echo "Downloading Hysteria for architecture: $HYSTERIA_ARCH" && \
    curl -L -o /etc/hysteria/hysteria "https://github.com/apernet/hysteria/releases/latest/download/hysteria-linux-${HYSTERIA_ARCH}" && \
    chmod +x /etc/hysteria/hysteria

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Make start script executable
RUN chmod +x start.sh

# Expose ports for Hysteria (default ports)
EXPOSE 443/udp 443/tcp

# Use start script as entrypoint
CMD ["./start.sh"]
