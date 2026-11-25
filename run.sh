#!/usr/bin/env bash
# One-step simple command to launch the Day Trader project effectively.
set -e

# Navigate to the project directory
cd "$(dirname "$0")"

# Launch the unified real-time dashboard station
exec python3 start.py "$@"
