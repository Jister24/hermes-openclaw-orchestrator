#!/bin/bash
cd /home/jister/hermes-openclaw-orchestrator
source venv/bin/activate
python run.py > ~/.orchestrator.log 2>&1 &
echo "Started PID=$!"
sleep 3
curl -s http://localhost:8080/health
