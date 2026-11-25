#!/usr/bin/env python3
"""
Tunnel Supervisor & Keep-Alive Daemon
Maintains a reliable public tunnel to localhost:8080 using localhost.run.
Automatically reconnects on drops and pings the tunnel to maintain web activity.
"""

import os
import re
import sys
import time
import subprocess
import urllib.request
from pathlib import Path

URL_FILE = Path("/tmp/current_tunnel_url.txt")
STATE_URL_FILE = Path(__file__).resolve().parent / "state" / "current_tunnel_url.txt"

def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)

def main():
    log("Starting Tunnel Supervisor Daemon...")
    
    while True:
        cmd = [
            "ssh",
            "-T",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=4",
            "-R", "80:localhost:8080",
            "nokey@localhost.run"
        ]
        
        log("Spawning ssh tunnel to localhost.run...")
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        last_ping = time.time()
        current_url = None
        
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            
            # Detect assigned tunnel URL
            match = re.search(r'([a-z0-9]+\.app\.lhr\.life)', line)
            if match:
                domain = match.group(1)
                current_url = f"https://{domain}"
                URL_FILE.write_text(current_url, encoding="utf-8")
                try:
                    STATE_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
                    STATE_URL_FILE.write_text(current_url, encoding="utf-8")
                except Exception:
                    pass
                log(f"★ TUNNEL ACTIVE: {current_url}")
            
            # Keep web activity alive by pinging every 45 seconds
            now = time.time()
            if current_url and (now - last_ping > 45):
                last_ping = now
                try:
                    req = urllib.request.Request(current_url, headers={"User-Agent": "TunnelKeepAlive/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        log(f"Keep-alive ping to {current_url}: status {resp.status}")
                except Exception as e:
                    log(f"Keep-alive ping notice: {e}")
        
        ret = proc.wait()
        log(f"Tunnel connection closed (exit code {ret}). Reconnecting in 3 seconds...")
        time.sleep(3)

if __name__ == "__main__":
    main()
