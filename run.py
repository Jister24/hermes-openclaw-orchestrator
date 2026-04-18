#!/usr/bin/env python3
"""Run the Hermes-OpenClaw Orchestrator."""

import os
import sys

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import uvicorn
from api.main import app

HOST = os.getenv("ORCHESTRATOR_HOST", "0.0.0.0")
PORT = int(os.getenv("ORCHESTRATOR_PORT", "8080"))

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=True,
    )
