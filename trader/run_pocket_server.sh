#!/data/data/com.termux/files/usr/bin/bash
if command -v pocketserver >/dev/null 2>&1; then
    exec pocketserver
fi
cd ~/day-trader-skill 2>/dev/null || cd /sdcard/day-trader-skill
echo "Starting Day Trader Pocket Server on http://localhost:8080..."
python3 start.py --host 0.0.0.0 --port 8080
