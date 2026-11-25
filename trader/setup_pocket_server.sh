#!/data/data/com.termux/files/usr/bin/bash
# Day Trader Pocket Server - Termux Automated Setup
set -e

echo "=========================================================="
echo "      ⚡ DAY TRADER POCKET SERVER (TERMUX ANDROID) ⚡     "
echo "=========================================================="

echo "[1/5] Updating Termux packages..."
pkg update -y || true

echo "[2/5] Installing Python and required build tools..."
pkg install -y python python-pip git curl || true

echo "[3/5] Installing Python web server dependencies..."
pip install aiohttp requests || pip install --break-system-packages aiohttp requests || true

echo "[4/5] Syncing project to Termux internal storage..."
mkdir -p ~/day-trader-skill
cp -rf /sdcard/day-trader-skill/* ~/day-trader-skill/ 2>/dev/null || true

cd ~/day-trader-skill
chmod +x start.py trader*/*.py 2>/dev/null || true

echo "[5/5] Registering global 'pocketserver' command..."
BIN_DIR="${PREFIX:-/data/data/com.termux/files/usr}/bin"
mkdir -p "$BIN_DIR"
cat << 'EOF' > "$BIN_DIR/pocketserver"
#!/data/data/com.termux/files/usr/bin/bash
echo "=========================================================="
echo "      ⚡ STARTING DAY TRADER POCKET SERVER ⚡             "
echo "=========================================================="
# Sync latest files if present in /sdcard/day-trader-skill
if [ -d /sdcard/day-trader-skill ]; then
    cp -rf /sdcard/day-trader-skill/* ~/day-trader-skill/ 2>/dev/null || true
fi
cd ~/day-trader-skill
python3 start.py --host 0.0.0.0 --port 8080
EOF
chmod +x "$BIN_DIR/pocketserver"

# Also add alias to ~/.bashrc and ~/.bash_profile
mkdir -p ~
echo "alias pocketserver='pocketserver'" >> ~/.bashrc 2>/dev/null || true
echo "alias pocketserver='pocketserver'" >> ~/.bash_profile 2>/dev/null || true

echo "=========================================================="
echo "Pocket Server Ready! You can now type 'pocketserver' anytime!"
echo "Starting Day Trader Station on Phone..."
echo "Open your phone browser at: http://localhost:8080"
echo "=========================================================="
pocketserver
