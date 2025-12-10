#!/bin/bash

# Kill the Python process running on port 5985

PORT=5985
echo "[*] Checking for process on port $PORT..."

# Find PID listening on the port
PID=$(netstat -ano | grep ":$PORT.*LISTENING" | awk '{print $NF}' | head -1)

if [ -z "$PID" ]; then
    echo "[OK] No process found on port $PORT"
    exit 0
fi

echo "[*] Found process PID: $PID"
echo "[*] Killing process..."

taskkill /PID "$PID" /F

if [ $? -eq 0 ]; then
    echo "[OK] Process killed successfully"
else
    echo "[ERROR] Failed to kill process"
    exit 1
fi
