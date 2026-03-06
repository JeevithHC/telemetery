# Fleet Telemetry System v2 — Windows Setup Guide
# =================================================
# Team: Shamantak | Jeevith | JOYSter | Bhoomi
# Stack: FastAPI + MongoDB + Redis + Streamlit
# =================================================


# ══════════════════════════════════════════════════
# STEP 1 — Install Python 3.11+
# ══════════════════════════════════════════════════
# Download from: https://www.python.org/downloads/
# During install → check "Add Python to PATH"
# Verify in a new terminal:
python --version


# ══════════════════════════════════════════════════
# STEP 2 — Install MongoDB (Community Edition)
# ══════════════════════════════════════════════════
# Download MSI from:
#   https://www.mongodb.com/try/download/community
#   Edition: Community  |  Version: 7.x  |  Platform: Windows
#
# During install:
#   ✅ Check "Install MongoDB as a Windows Service"  ← IMPORTANT
#   ✅ Check "Install MongoDB Compass" (optional GUI)
#
# After install MongoDB starts automatically.
# To verify it is running, open a terminal and run:
mongosh
# You should see the MongoDB shell. Type exit to quit.
# If mongosh is not found, add to PATH:
#   C:\Program Files\MongoDB\Server\7.0\bin


# ══════════════════════════════════════════════════
# STEP 3 — Install Redis (Memurai — native Windows)
# ══════════════════════════════════════════════════
# Memurai is a Redis-compatible server for Windows.
# Download free edition from: https://www.memurai.com/get-memurai
# Install it — it registers as a Windows Service automatically.
#
# To verify Redis is running:
memurai-cli ping
# Expected response: PONG
#
# Alternative: if you already have WSL2, use:
#   wsl sudo service redis-server start
#   wsl redis-cli ping


# ══════════════════════════════════════════════════
# STEP 4 — Create project folder and install packages
# ══════════════════════════════════════════════════

# Open Command Prompt or PowerShell, then:
mkdir C:\telemetry_project
cd C:\telemetry_project

# Copy all 5 .py files + requirements.txt into this folder, then:
pip install -r requirements.txt


# ══════════════════════════════════════════════════
# STEP 5 — Verify services are running
# ══════════════════════════════════════════════════

# MongoDB check (should print databases):
mongosh --eval "db.adminCommand({listDatabases:1})"

# Redis check (should print PONG):
memurai-cli ping


# ══════════════════════════════════════════════════
# STEP 6 — Run the system (3 separate terminals)
# ══════════════════════════════════════════════════

# ── Terminal 1: Start the FastAPI backend ──────────
cd C:\telemetry_project
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Verify API is up: open browser → http://localhost:8000
# You should see: {"message":"Vehicle Telemetry API v2","version":"2.0.0"}


# ── Terminal 2: Start the vehicle simulator ────────
cd C:\telemetry_project
python simulator.py

# You will see 100 vehicles printing live data every second.
# Let it run for at least 2-3 minutes before opening the dashboard.


# ── Terminal 3: Start the Streamlit dashboard ──────
cd C:\telemetry_project
streamlit run dashboard.py

# Browser opens automatically at: http://localhost:8501
# Login: admin / 1234


# ══════════════════════════════════════════════════
# STEP 7 — Run downsampling (optional, run manually)
# ══════════════════════════════════════════════════

# Run this in a 4th terminal after the simulator has been
# running for at least 1 minute:
cd C:\telemetry_project
python downsampling.py

# This compresses older data into aggregated tiers.
# Run it periodically, or set up a Windows Task Scheduler job.


# ══════════════════════════════════════════════════
# FILE STRUCTURE
# ══════════════════════════════════════════════════

# C:\telemetry_project\
# ├── database.py        MongoDB + Redis connections
# ├── main.py            FastAPI backend (13 endpoints)
# ├── simulator.py       100-vehicle physics simulator
# ├── downsampling.py    4-level data aggregation pipeline
# ├── dashboard.py       Streamlit 6-tab dashboard
# └── requirements.txt   Python dependencies


# ══════════════════════════════════════════════════
# DASHBOARD FEATURES
# ══════════════════════════════════════════════════

# Tab 1 — Vehicle Lookup
#   Type a Vehicle ID (e.g. TRUCK-001, CAR-005, BUS-003)
#   Click "Present Time" to see live data
#   Click "Download PDF" to get a driver safety report
#   Or click "Fetch Past Data" and pick a date/time

# Tab 2 — Fleet Summary
#   Fleet KPIs: speed, temp, fuel, health averages
#   Predictive Maintenance cards (colour-coded risk)
#   Health Matrix (all 100 vehicles at a glance)
#   Fuel Cost Calculator (enter price per litre)

# Tab 3 — Live Charts
#   Pick any vehicle + time window + chart group
#   6 chart groups: Core, Driver, Engine, Tyres, Resources, Scores

# Tab 4 — Fleet Map
#   All 100 vehicles on Chennai map
#   Green = healthy, Orange = fair, Red = needs maintenance

# Tab 5 — Alerts
#   Filter by vehicle, severity, resolved status
#   9 alert types: temp, speed, fuel, battery, idle,
#                  accident, oil, tyre, maintenance

# Tab 6 — Fleet Analytics
#   Fleet-wide trend lines (health, safety, speed, fuel over time)
#   Vehicle type comparison bar charts
#   Full risk ranking table (worst health first)
#   Top 5 healthiest / Bottom 5 most at-risk


# ══════════════════════════════════════════════════
# TROUBLESHOOTING
# ══════════════════════════════════════════════════

# "mongosh not found"
#   → Add C:\Program Files\MongoDB\Server\7.0\bin to PATH

# "uvicorn not found"
#   → pip install uvicorn  (or check pip install -r requirements.txt ran correctly)

# "Connection refused" in dashboard
#   → Make sure uvicorn main:app is running in Terminal 1

# "Redis connection error"
#   → Check Memurai service: open Services → look for Memurai → Start
#   → Or in PowerShell: Start-Service Memurai

# MongoDB service not running
#   → In PowerShell (run as Administrator):
#      Start-Service MongoDB
#   → Or: open Services app → find MongoDB → Start

# Port 8000 already in use
#   → netstat -ano | findstr :8000
#   → taskkill /PID <pid_number> /F
#   → Then restart uvicorn

# Port 8501 already in use (Streamlit)
#   → streamlit run dashboard.py --server.port 8502


# ══════════════════════════════════════════════════
# QUICK RESTART (after first setup)
# ══════════════════════════════════════════════════

# MongoDB and Redis start automatically with Windows.
# Just open 3 terminals and run:
#
#   Terminal 1:  uvicorn main:app --reload
#   Terminal 2:  python simulator.py
#   Terminal 3:  streamlit run dashboard.py
