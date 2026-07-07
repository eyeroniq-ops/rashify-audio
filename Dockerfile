FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget ca-certificates curl unzip && \
    rm -rf /var/lib/apt/lists/*

# Download slskd binary
RUN SLSKD_VER="0.25.1" && \
    wget -q -O /tmp/slskd.zip \
    "https://github.com/slskd/slskd/releases/download/${SLSKD_VER}/slskd-${SLSKD_VER}-linux-x64.zip" && \
    mkdir -p /app/slskd && \
    cd /app/slskd && unzip -o /tmp/slskd.zip && \
    chmod +x /app/slskd/slskd && \
    rm /tmp/slskd.zip

RUN mkdir -p /app/downloads /app/incomplete

RUN pip3 install --no-cache-dir flask flask-cors requests

COPY slskd.yml /app/slskd/slskd.yml
COPY server.py start.sh /app/
RUN chmod +x /app/start.sh

EXPOSE 8080
CMD ["/app/start.sh"]
