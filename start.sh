#!/bin/sh

echo "=== Setting up slskd ==="
cd /app/slskd
mkdir -p /app/downloads /app/incomplete

# slskd 0.25.1 looks for config in ~/.local/share/slskd/
mkdir -p /root/.local/share/slskd/
cp /app/slskd/slskd.yml /root/.local/share/slskd/slskd.yml
echo "Config copied to /root/.local/share/slskd/slskd.yml"

# .NET globalization fix
export DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=1

echo "=== Starting slskd ==="
./slskd > /tmp/slskd-stdout.log 2> /tmp/slskd-stderr.log &
SLSKD_PID=$!
echo "slskd PID: $SLSKD_PID"
sleep 8

if kill -0 $SLSKD_PID 2>/dev/null; then
  echo "slskd running OK"
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s http://localhost:5030/api/v0/application > /dev/null 2>&1; then
      echo "slskd API ready after ${i}s"
      break
    fi
    sleep 1
  done
else
  echo "slskd CRASHED!"
  cat /tmp/slskd-stderr.log 2>/dev/null | tail -20
fi

echo "=== Starting Python API on :8080 ==="
cd /app
exec python3 server.py
