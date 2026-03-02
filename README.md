# 🚗 Vehicle Telemetry System

A real-time vehicle telemetry backend built with **FastAPI**, **MongoDB Atlas**, and a **Streamlit** dashboard. Simulates 100 vehicles sending live operational data with a realistic physics model and a 5-tier hot-cold storage architecture.

---

## 📸 Dashboard Preview

> Login → Search any vehicle → View live or historical data across all storage layers

---

## 🏗️ System Architecture

```
┌─────────────────────┐
│   simulator.py      │  ← 100 vehicles sending data every second (in this simulation can easily hold upto 10,000)
│   (Physics Model)   │
└────────┬────────────┘
         │ POST /api/telemetry
         ▼
┌─────────────────────┐
│   FastAPI Backend   │  ← Validates, stores, serves telemetry
│   main.py           │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐     ┌─────────────────────┐
│   MongoDB Atlas     │ ←── │  downsampling.py     │
│   (Cloud Database)  │     │  (4-level aggregation│
└────────┬────────────┘     └─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Streamlit Dashboard│  ← Vehicle lookup, fleet summary, charts
│  dashboard.py       │
└─────────────────────┘
```

---

## 🔥 Hot-Cold Storage Architecture

| Layer | Data Type | Retention | Description |
|-------|-----------|-----------|-------------|
| 🔥 Hot | Raw (per second) | 1 hour | Every second reading |
| 🌡️ Warm | Per minute avg | 1 day | Minute-level summaries |
| ❄️ Cold | Hourly avg | 3 days | Hour-level summaries |
| 🧊 Archive | Daily avg | 1 year | Day-level summaries |
| 📦 Permanent | Yearly avg | Forever | Year-level summaries |

---

## 🚙 Physics Model

Each vehicle generates **logically consistent** telemetry:

| Metric | Logic |
|--------|-------|
| **Temperature** | Starts at 25°C (ambient), rises with running hours + speed |
| **RPM** | Directly correlated with speed ratio per vehicle type |
| **Fuel Level** | Decreases based on speed load over time |
| **Battery** | Slow drain over running time |
| **Speed** | Smooth acceleration/deceleration, stays in mode 30–120 seconds |

### Vehicle Profiles

| Type | Max Speed | RPM Range | Temp Range |
|------|-----------|-----------|------------|
| TRUCK | 100 km/h | 750–2500 | 25–115°C |
| CAR | 140 km/h | 700–4500 | 25–105°C |
| VAN | 120 km/h | 750–3500 | 25–110°C |

### Driving Modes
- **Highway** — sustained high speed (70–95% of max), held for 30–120 seconds
- **City** — stop-start low speed (10–45% of max)
- **Idle** — speed = 0, engine at idle RPM
- **Braking** — gradual deceleration

---

## 📡 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `POST` | `/api/telemetry` | Ingest telemetry from vehicle |
| `GET` | `/api/telemetry/{vehicle_id}` | Recent raw data (by minutes) |
| `GET` | `/api/telemetry/{vehicle_id}/latest` | Latest single reading |
| `GET` | `/api/telemetry/{vehicle_id}/smart` | Auto storage-layer retrieval by datetime |
| `GET` | `/api/telemetry/{vehicle_id}/{data_type}` | Get aggregated data (minute/hourly/daily/yearly) |
| `GET` | `/api/vehicles/summary` | Latest reading for all active vehicles |

---

## 🖥️ Dashboard Features

- **🔍 Vehicle Lookup** — search any vehicle by ID, present time button for live reading, past data with automatic storage layer detection
- **🚘 Fleet Summary** — fleet-wide averages + full vehicle list with all metrics
- **📈 Live Charts** — real-time line charts for speed, temperature, RPM, fuel, battery, run time
- **🔐 Login system** — simple authentication gate
- **● API Status** — live indicator in sidebar showing backend connectivity

---

## 🗂️ Project Structure

```
telemetery/
│
├── simulator.py       # 100-vehicle physics simulator
├── main.py            # FastAPI backend (all endpoints)
├── database.py        # MongoDB Atlas connection + indexing
├── downsampling.py    # 4-level data aggregation script
├── dashboard.py       # Streamlit frontend dashboard
├── .gitignore         # Excludes .env and cache files
└── README.md
```

---

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.12+
- MongoDB Atlas account (free tier)
- Anaconda (recommended)

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/vehicle-telemetry.git
cd vehicle-telemetry
```

### 2. Install dependencies
```bash
pip install fastapi uvicorn pymongo python-dotenv streamlit requests pandas
```

### 3. Configure MongoDB

Create a `.env` file in the project root:
```
MONGO_URI=mongodb+srv://YOUR_USERNAME:YOUR_PASSWORD@your-cluster.mongodb.net/?appName=your-cluster
DB_NAME=vehicle_telemetry
COLLECTION_NAME=telemetry
```

> ⚠️ Never commit your `.env` file. It is excluded via `.gitignore`.

### 4. Run the system

**Terminal 1 — Start the API:**
```bash
uvicorn main:app --reload
```

**Terminal 2 — Start the simulator:**
```bash
python3 simulator.py
```

**Terminal 3 — Start the dashboard:**
```bash
streamlit run dashboard.py
```

### 5. Open the dashboard
```
http://localhost:8501
```

**Login credentials:**
- Username: `admin`
- Password: `1234`

---

## 🔄 Downsampling

Run manually to aggregate and clean up old data:
```bash
python3 downsampling.py
```

To automate on Mac (runs every minute via cron):
```bash
crontab -e
# Add this line:
* * * * * /usr/bin/python3 /path/to/your/project/downsampling.py
```

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Uvicorn |
| Database | MongoDB Atlas |
| Frontend | Streamlit |
| Simulator | Python threading |
| Data Validation | Pydantic |
| Language | Python 3.12 |

---

## 👤 Author

**Shamantak** — Led the overall project from conception to delivery — overseeing project planning, sprint organization, and technical direction. Contributed directly to backend development and produced the core research documentation.

**Bhoomi** — Front-end Designer, looked after the interactice stream-lit Interface - including real-time data binding, storage layer routing, fleet summary views, live telemetry charts, and the authenticated user interface.

**Joyster** — Engineered the full-stack integration between the backend API and the Streamlit frontend dashboard, realistic physics-based vehicle simulator .

**Jeevith** — Built as part of a backend systems and IoT data engineering project, FastAPI REST API with 5-tier hot-cold storage architecture, MongoDB Atlas database design, and the automated downsampling pipeline.