"""
main.py — Vehicle Telemetry FastAPI Backend v3
================================================
NEW in v3:
  WebSocket endpoint    → persistent vehicle connections, zero HTTP overhead
  Batch ingestion       → receive array of readings in one call (scalable)
  Geospatial query      → find all vehicles within N km of a GPS point
  Anomaly detection     → Isolation Forest ML model per vehicle type
  Edge computing stat   → tracks how many readings were suppressed at edge

Total endpoints: 17
─────────────────────────────────────────────
POST /api/telemetry              single reading (HTTP, kept for compatibility)
POST /api/telemetry/batch        array of readings in one call
WS   /ws/telemetry/{id}          persistent WebSocket stream (preferred)
GET  /api/telemetry/{id}/latest  Redis-first latest reading
GET  /api/telemetry/{id}         raw data by minutes back
GET  /api/telemetry/{id}/smart   auto storage-layer by datetime
GET  /api/vehicles/summary       full fleet aggregation
GET  /api/vehicles/locations     GPS coords for map
GET  /api/vehicles/nearby        vehicles within radius (geospatial)
GET  /api/alerts                 filtered alert retrieval
GET  /api/alerts/count           bell badge count
PATCH /api/alerts/{id}/resolve   mark alert resolved
GET  /api/telemetry/{id}/{type}  aggregated tier data
GET  /api/analytics/fleet-overview    per-type stats
GET  /api/analytics/maintenance-risk  risk ranking
GET  /api/analytics/trends            per-minute averages
GET  /api/analytics/edge-stats        edge computing savings report
"""

import json
import asyncio
import numpy as np
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from collections import defaultdict
from database import collection, alerts_col, redis_client

app = FastAPI(title="Vehicle Telemetry API v3", version="3.0.0")

# ── In-memory state ────────────────────────────────────────
vehicle_prev_speed   = {}
vehicle_idle_seconds = {}

# ── Edge computing stats ───────────────────────────────────
edge_stats = {
    "total_generated":  0,   # readings simulator computed
    "total_sent":       0,   # readings actually transmitted
    "suppressed":       0,   # readings dropped by edge logic
    "bandwidth_saved_pct": 0.0
}

# ── ML: Isolation Forest per vehicle type ──────────────────
try:
    from sklearn.ensemble import IsolationForest
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("⚠️  scikit-learn not installed → pip install scikit-learn")

# Features used for anomaly detection
ANOMALY_FEATURES = [
    "speed", "rpm", "engine_temp", "coolant_temp",
    "oil_pressure", "engine_vibration", "fuel_level"
]
TRAIN_AFTER = 300          # train model after 300 readings per vehicle type
isolation_models  = {}     # { vehicle_type: IsolationForest }
training_buffer   = defaultdict(list)  # { vehicle_type: [[features], ...] }

def extract_features(doc: dict) -> list:
    return [float(doc.get(f, 0) or 0) for f in ANOMALY_FEATURES]

def check_anomaly(doc: dict):
    """
    Returns (is_anomaly: bool, score: float).
    Score closer to -1 = more anomalous.
    Trains the Isolation Forest once TRAIN_AFTER readings per type are seen.
    """
    if not ML_AVAILABLE:
        return False, 0.0

    vtype    = doc.get("vehicle_type", "CAR")
    features = extract_features(doc)
    training_buffer[vtype].append(features)

    # Train model when threshold reached
    if len(training_buffer[vtype]) == TRAIN_AFTER:
        print(f"[ML] Training Isolation Forest for {vtype} on {TRAIN_AFTER} samples...")
        model = IsolationForest(
            n_estimators=100,
            contamination=0.05,   # expect ~5% anomalies
            random_state=42
        )
        model.fit(training_buffer[vtype])
        isolation_models[vtype] = model
        print(f"[ML] {vtype} model trained ✅")

    if vtype not in isolation_models:
        return False, 0.0

    model      = isolation_models[vtype]
    prediction = model.predict([features])[0]       # 1=normal, -1=anomaly
    score      = float(model.score_samples([features])[0])
    is_anomaly = prediction == -1
    return is_anomaly, score


# ── Alert thresholds ───────────────────────────────────────
TEMP_LIMITS  = {"SCOOTY":95,"BIKE":100,"CAR":105,"PICKUP":110,"VAN":110,"TRUCK":115,"BUS":118}
SPEED_LIMITS = {"SCOOTY":60,"BIKE":120,"CAR":140,"PICKUP":130,"VAN":120,"TRUCK":100,"BUS":90}
LOW_FUEL_PCT        = 10.0
LOW_BATTERY_PCT     = 15.0
IDLE_ALERT_SECS     = 600
ACCIDENT_DROP_KMH   = 40.0
LOW_OIL_PSI         = 20.0
LOW_TYRE_DEVIATION  = 0.20


# ── Pydantic model ─────────────────────────────────────────
class TelemetryInput(BaseModel):
    vehicle_id:    str
    vehicle_type:  str  = "CAR"
    timestamp:     Optional[datetime] = None
    data_type:     str  = "raw"
    latitude:      float = 0.0
    longitude:     float = 0.0
    heading:       float = 0.0
    gps_signal:    float = 100.0
    speed:         float = Field(..., ge=0, le=400)
    rpm:           float = Field(..., ge=0, le=12000)
    driving_mode:  str   = "unknown"
    running_hours: float = Field(..., ge=0)
    odometer:      float = Field(default=0, ge=0)
    engine_temp:   float = Field(..., ge=0, le=300)
    coolant_temp:  float = Field(default=25.0, ge=0)
    ambient_temp:  float = Field(default=30.0)
    oil_pressure:         float = Field(default=50.0, ge=0)
    engine_vibration:     float = Field(default=0.0,  ge=0)
    turbo_boost:          float = Field(default=0.0,  ge=0)
    alternator_voltage:   float = Field(default=14.0)
    brake_pressure:        float = Field(default=0.0, ge=0, le=100)
    accelerator_pct:       float = Field(default=0.0, ge=0, le=100)
    clutch_shifts_per_min: float = Field(default=0.0, ge=0)
    steering_angle:        float = Field(default=0.0)
    harsh_braking:         bool  = False
    harsh_acceleration:    bool  = False
    load_weight_pct:  float = Field(default=0.0, ge=0, le=100)
    tyre_pressure_fl: float = Field(default=32.0, ge=0)
    tyre_pressure_fr: float = Field(default=32.0, ge=0)
    tyre_pressure_rl: float = Field(default=32.0, ge=0)
    tyre_pressure_rr: float = Field(default=32.0, ge=0)
    fuel_level:    float = Field(..., ge=0, le=100)
    battery_level: float = Field(..., ge=0, le=100)
    headwind_speed: float = Field(default=0.0, ge=0)
    driver_safety_score:  float = Field(default=100.0, ge=0, le=100)
    health_score:         float = Field(default=100.0, ge=0, le=100)
    maintenance_required: bool  = False
    # Edge computing fields
    edge_suppressed: int = Field(default=0, ge=0)   # readings skipped before this one


# ── Helpers ────────────────────────────────────────────────
def serialize(doc) -> dict:
    if doc is None:
        return {}
    doc["_id"] = str(doc["_id"])
    for f in ["timestamp", "period_start", "period_end"]:
        if isinstance(doc.get(f), datetime):
            doc[f] = doc[f].isoformat()
    return doc


def get_storage_layer(dt: datetime):
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    diff = now - dt
    if   diff <= timedelta(hours=1):  return "hot",       "raw",    "🔥 HOT STORAGE (per-second)"
    elif diff <= timedelta(days=1):   return "warm",      "minute", "🌡 WARM STORAGE (per-minute)"
    elif diff <= timedelta(days=3):   return "cold",      "hourly", "❄ COLD STORAGE (hourly)"
    elif diff <= timedelta(days=365): return "archive",   "daily",  "🧊 ARCHIVE STORAGE (daily)"
    else:                             return "permanent", "yearly", "📦 PERMANENT STORAGE (yearly)"


def create_alert(vid, alert_type, severity, message, snapshot):
    alerts_col.insert_one({
        "vehicle_id":    vid,
        "vehicle_type":  snapshot.get("vehicle_type", ""),
        "alert_type":    alert_type,
        "severity":      severity,
        "message":       message,
        "timestamp":     datetime.now(timezone.utc),
        "resolved":      False,
        "data_snapshot": snapshot
    })


def run_alert_checks(data: dict):
    vid   = data.get("vehicle_id", "")
    vtype = data.get("vehicle_type", "CAR").upper()
    snap  = {
        "vehicle_type": vtype,
        "speed":         data.get("speed", 0),
        "engine_temp":   data.get("engine_temp", 0),
        "coolant_temp":  data.get("coolant_temp", 0),
        "rpm":           data.get("rpm", 0),
        "fuel_level":    data.get("fuel_level", 0),
        "battery_level": data.get("battery_level", 0),
        "oil_pressure":  data.get("oil_pressure", 0),
        "health_score":  data.get("health_score", 100),
        "tyre_fl":       data.get("tyre_pressure_fl", 32),
        "tyre_fr":       data.get("tyre_pressure_fr", 32),
        "tyre_rl":       data.get("tyre_pressure_rl", 32),
        "tyre_rr":       data.get("tyre_pressure_rr", 32),
        "running_hours": data.get("running_hours", 0),
        "driving_mode":  data.get("driving_mode", ""),
    }

    if data.get("engine_temp", 0) > TEMP_LIMITS.get(vtype, 110):
        create_alert(vid, "HIGH_ENGINE_TEMP", "critical",
            f"Engine temp {data.get('engine_temp')}C exceeds limit", snap)

    if data.get("speed", 0) > SPEED_LIMITS.get(vtype, 120):
        create_alert(vid, "OVER_SPEED", "warning",
            f"Speed {data.get('speed')} km/h exceeds limit", snap)

    fl = data.get("fuel_level", 100)
    if 0 < fl < LOW_FUEL_PCT:
        create_alert(vid, "LOW_FUEL", "warning", f"Fuel critically low: {fl}%", snap)

    if data.get("battery_level", 100) < LOW_BATTERY_PCT:
        create_alert(vid, "LOW_BATTERY", "warning",
            f"Battery low: {data.get('battery_level')}%", snap)

    if data.get("speed", 0) == 0:
        vehicle_idle_seconds[vid] = vehicle_idle_seconds.get(vid, 0) + 1
        if vehicle_idle_seconds[vid] == IDLE_ALERT_SECS:
            create_alert(vid, "EXTENDED_IDLE", "warning", "Vehicle idle >10 minutes", snap)
    else:
        vehicle_idle_seconds[vid] = 0

    prev = vehicle_prev_speed.get(vid)
    spd  = data.get("speed", 0)
    if prev is not None:
        drop = prev - spd
        if drop >= ACCIDENT_DROP_KMH and data.get("rpm", 0) > 0 and prev > 20:
            create_alert(vid, "ACCIDENT_DETECTED", "critical",
                f"ACCIDENT! Speed dropped from {prev} to {spd} km/h", snap)
    vehicle_prev_speed[vid] = spd

    if data.get("oil_pressure", 100) < LOW_OIL_PSI:
        create_alert(vid, "LOW_OIL_PRESSURE", "critical",
            f"Oil pressure critical: {data.get('oil_pressure')} PSI", snap)

    normal_tyres = {
        "SCOOTY":(30,28),"BIKE":(32,30),"CAR":(32,32),
        "PICKUP":(35,38),"VAN":(38,42),"TRUCK":(100,110),"BUS":(100,110)
    }
    nf, nr = normal_tyres.get(vtype, (32,32))
    for label, psi, normal in [
        ("FL", data.get("tyre_pressure_fl", nf), nf),
        ("FR", data.get("tyre_pressure_fr", nf), nf),
        ("RL", data.get("tyre_pressure_rl", nr), nr),
        ("RR", data.get("tyre_pressure_rr", nr), nr),
    ]:
        if psi < normal * (1 - LOW_TYRE_DEVIATION):
            create_alert(vid, f"LOW_TYRE_{label}", "warning",
                f"Tyre {label} low: {psi:.1f} PSI", snap)

    if data.get("maintenance_required"):
        key = f"maint_alerted:{vid}"
        if not redis_client.get(key):
            create_alert(vid, "MAINTENANCE_REQUIRED", "warning",
                f"Health score {data.get('health_score')} — maintenance required", snap)
            redis_client.setex(key, 600, "1")

    # ML Anomaly alert
    is_anomaly, score = check_anomaly(data)
    if is_anomaly:
        alert_key = f"anomaly_alerted:{vid}"
        if not redis_client.get(alert_key):
            create_alert(vid, "ML_ANOMALY", "critical",
                f"Isolation Forest anomaly detected (score: {score:.3f}). "
                f"Unusual combination of: speed={data.get('speed')}, "
                f"rpm={data.get('rpm')}, temp={data.get('engine_temp')}",
                {**snap, "anomaly_score": score})
            redis_client.setex(alert_key, 120, "1")   # cooldown 2 min


def process_single(data: dict) -> str:
    """Write one telemetry reading to MongoDB + Redis. Returns inserted id."""
    now = data.get("timestamp") or datetime.now(timezone.utc)
    if isinstance(now, str):
        try:
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        except Exception:
            now = datetime.now(timezone.utc)

    doc              = dict(data)
    doc["timestamp"] = now
    doc["data_type"] = "raw"

    # Store GeoJSON Point for geospatial queries
    lat = data.get("latitude", 0)
    lon = data.get("longitude", 0)
    if lat != 0 or lon != 0:
        doc["location"] = {
            "type":        "Point",
            "coordinates": [lon, lat]   # MongoDB uses [longitude, latitude]
        }

    # Update edge stats
    suppressed = int(data.get("edge_suppressed", 0))
    edge_stats["total_sent"]      += 1
    edge_stats["suppressed"]      += suppressed
    edge_stats["total_generated"] += (1 + suppressed)
    total = edge_stats["total_generated"]
    if total > 0:
        edge_stats["bandwidth_saved_pct"] = round(
            edge_stats["suppressed"] / total * 100, 1
        )

    result = collection.insert_one(doc)
    vid    = data.get("vehicle_id", "")

    # Cache in Redis
    cache_doc = {
        k: (v.isoformat() if isinstance(v, datetime) else v)
        for k, v in doc.items()
        if k != "location"
    }
    cache_doc["_id"] = str(result.inserted_id)
    redis_client.setex(f"vehicle:latest:{vid}", 90, json.dumps(cache_doc))

    # Anomaly score in Redis for dashboard to read without re-computing
    is_anomaly, score = check_anomaly(data)
    if is_anomaly:
        redis_client.setex(f"anomaly:{vid}", 120, json.dumps({
            "score": score, "anomaly": True,
            "speed": data.get("speed"), "rpm": data.get("rpm"),
            "engine_temp": data.get("engine_temp")
        }))

    run_alert_checks(data)
    return str(result.inserted_id)


# ════════════════════════════════════════════════════════════
# WebSocket Connection Manager
# ════════════════════════════════════════════════════════════

class WSManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, vehicle_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[vehicle_id] = ws
        print(f"[WS] {vehicle_id} connected  | active={len(self.connections)}")

    def disconnect(self, vehicle_id: str):
        self.connections.pop(vehicle_id, None)
        print(f"[WS] {vehicle_id} disconnected | active={len(self.connections)}")

    async def send_ack(self, vehicle_id: str, count: int):
        ws = self.connections.get(vehicle_id)
        if ws:
            try:
                await ws.send_json({"status": "ok", "count": count})
            except Exception:
                pass

ws_manager = WSManager()


# ════════════════════════════════════════════════════════════
# ROUTES
# ════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {
        "message": "Vehicle Telemetry API v3",
        "version": "3.0.0",
        "status":  "running",
        "features": ["websocket", "batch_ingestion", "geospatial", "ml_anomaly", "edge_computing"]
    }


# ── WebSocket endpoint (preferred for simulator) ───────────
@app.websocket("/ws/telemetry/{vehicle_id}")
async def ws_telemetry(websocket: WebSocket, vehicle_id: str):
    """
    Persistent WebSocket connection per vehicle.
    Simulator sends a JSON array (batch) every 5 seconds.
    Server processes each reading and sends back an ack.
    """
    await ws_manager.connect(vehicle_id, websocket)
    try:
        while True:
            raw  = await websocket.receive_text()
            data = json.loads(raw)

            # Accept both single reading and array (batch)
            batch = data if isinstance(data, list) else [data]
            count = 0
            for reading in batch:
                reading["vehicle_id"] = vehicle_id
                await asyncio.to_thread(process_single, reading)
                count += 1

            await ws_manager.send_ack(vehicle_id, count)

    except WebSocketDisconnect:
        ws_manager.disconnect(vehicle_id)
    except Exception as e:
        print(f"[WS ERROR] {vehicle_id}: {e}")
        ws_manager.disconnect(vehicle_id)


# ── Batch HTTP endpoint ────────────────────────────────────
@app.post("/api/telemetry/batch", status_code=201)
def receive_batch(readings: List[dict]):
    """
    Accepts an array of telemetry readings in one HTTP call.
    Reduces DB I/O: 100 vehicles × 5s batch = 20 requests/sec instead of 100.
    """
    if not readings:
        raise HTTPException(status_code=400, detail="Empty batch")
    if len(readings) > 500:
        raise HTTPException(status_code=400, detail="Batch too large (max 500)")

    ids = []
    for reading in readings:
        try:
            ids.append(process_single(reading))
        except Exception as e:
            print(f"[BATCH ERROR] {e}")

    return {"status": "success", "inserted": len(ids), "ids": ids}


# ── Single HTTP endpoint (kept for compatibility) ──────────
@app.post("/api/telemetry", status_code=201)
def receive_telemetry(data: TelemetryInput):
    doc = data.dict()
    inserted_id = process_single(doc)
    return {"status": "success", "id": inserted_id}


# ── Latest reading (Redis-first) ───────────────────────────
@app.get("/api/telemetry/{vehicle_id}/latest")
def get_latest(vehicle_id: str):
    cached = redis_client.get(f"vehicle:latest:{vehicle_id}")
    if cached:
        d = json.loads(cached)
        d["_source"] = "redis_cache"
        # Attach anomaly info if present
        anom = redis_client.get(f"anomaly:{vehicle_id}")
        if anom:
            d["anomaly_info"] = json.loads(anom)
        return d
    doc = collection.find_one(
        {"vehicle_id": vehicle_id, "data_type": "raw"},
        sort=[("timestamp", -1)]
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"No data for {vehicle_id}")
    r = serialize(doc)
    r["_source"] = "mongodb"
    return r


# ── Raw data by minutes ────────────────────────────────────
@app.get("/api/telemetry/{vehicle_id}")
def get_telemetry(vehicle_id: str, minutes: int = Query(default=10, ge=1, le=1440)):
    since  = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": "raw", "timestamp": {"$gte": since}},
        sort=[("timestamp", -1)]
    )
    records = [serialize(doc) for doc in cursor]
    if not records:
        raise HTTPException(status_code=404, detail=f"No data for {vehicle_id} in last {minutes} mins")
    return {"vehicle_id": vehicle_id, "minutes_back": minutes,
            "total_records": len(records), "data": records}


# ── Smart storage layer ────────────────────────────────────
@app.get("/api/telemetry/{vehicle_id}/smart")
def get_smart(vehicle_id: str, selected_datetime: str = Query(...)):
    try:
        dt = datetime.fromisoformat(selected_datetime)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format")
    _, data_type, label = get_storage_layer(dt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": data_type,
         "timestamp": {"$gte": dt, "$lte": datetime.now(timezone.utc)}},
        sort=[("timestamp", -1)], limit=100
    )
    records = [serialize(doc) for doc in cursor]
    return {"vehicle_id": vehicle_id, "storage_layer": label,
            "data_type": data_type, "total_records": len(records), "data": records}


# ── Fleet summary ──────────────────────────────────────────
@app.get("/api/vehicles/summary")
def get_summary():
    pipeline = [
        {"$match": {"data_type": "raw"}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id":                  "$vehicle_id",
            "vehicle_type":         {"$first": "$vehicle_type"},
            "speed":                {"$first": "$speed"},
            "engine_temp":          {"$first": "$engine_temp"},
            "rpm":                  {"$first": "$rpm"},
            "fuel_level":           {"$first": "$fuel_level"},
            "battery_level":        {"$first": "$battery_level"},
            "running_hours":        {"$first": "$running_hours"},
            "driving_mode":         {"$first": "$driving_mode"},
            "health_score":         {"$first": "$health_score"},
            "driver_safety_score":  {"$first": "$driver_safety_score"},
            "maintenance_required": {"$first": "$maintenance_required"},
            "oil_pressure":         {"$first": "$oil_pressure"},
            "latitude":             {"$first": "$latitude"},
            "longitude":            {"$first": "$longitude"},
            "last_seen":            {"$first": "$timestamp"}
        }}
    ]
    results = list(collection.aggregate(pipeline, allowDiskUse=True))
    return {
        "total_vehicles": len(results),
        "vehicles": [{
            "vehicle_id":           r["_id"],
            "vehicle_type":         r.get("vehicle_type",""),
            "speed":                r.get("speed", 0),
            "engine_temp":          r.get("engine_temp", 0),
            "rpm":                  r.get("rpm", 0),
            "fuel_level":           r.get("fuel_level", 0),
            "battery_level":        r.get("battery_level", 0),
            "running_hours":        r.get("running_hours", 0),
            "driving_mode":         r.get("driving_mode", ""),
            "health_score":         r.get("health_score", 100),
            "driver_safety_score":  r.get("driver_safety_score", 100),
            "maintenance_required": r.get("maintenance_required", False),
            "oil_pressure":         r.get("oil_pressure", 0),
            "latitude":             r.get("latitude", 0),
            "longitude":            r.get("longitude", 0),
            "last_seen":            r.get("last_seen", "")
        } for r in results]
    }


# ── GPS locations ──────────────────────────────────────────
@app.get("/api/vehicles/locations")
def get_locations():
    pipeline = [
        {"$match": {"data_type": "raw"}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id":                  "$vehicle_id",
            "vehicle_type":         {"$first": "$vehicle_type"},
            "latitude":             {"$first": "$latitude"},
            "longitude":            {"$first": "$longitude"},
            "speed":                {"$first": "$speed"},
            "health_score":         {"$first": "$health_score"},
            "maintenance_required": {"$first": "$maintenance_required"},
            "driving_mode":         {"$first": "$driving_mode"},
        }}
    ]
    results = list(collection.aggregate(pipeline, allowDiskUse=True))
    return {"vehicles": [{
        "vehicle_id":           r["_id"],
        "vehicle_type":         r.get("vehicle_type",""),
        "latitude":             r.get("latitude", 0),
        "longitude":            r.get("longitude", 0),
        "speed":                r.get("speed", 0),
        "health_score":         r.get("health_score", 100),
        "maintenance_required": r.get("maintenance_required", False),
        "driving_mode":         r.get("driving_mode", ""),
    } for r in results]}


# ── Geospatial: vehicles within radius ────────────────────
@app.get("/api/vehicles/nearby")
def get_nearby(
    lat:       float = Query(..., description="Center latitude"),
    lon:       float = Query(..., description="Center longitude"),
    radius_km: float = Query(default=5.0, ge=0.1, le=50.0)
):
    """
    Find all vehicles whose latest position is within radius_km of (lat, lon).
    Uses MongoDB 2dsphere index — real geospatial query, not a filter loop.
    Example: /api/vehicles/nearby?lat=13.08&lon=80.27&radius_km=5
    """
    radius_m = radius_km * 1000

    # Find most recent raw doc per vehicle within the sphere
    pipeline = [
        {"$match": {
            "data_type": "raw",
            "location": {
                "$nearSphere": {
                    "$geometry":    {"type": "Point", "coordinates": [lon, lat]},
                    "$maxDistance": radius_m
                }
            }
        }},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id":          "$vehicle_id",
            "vehicle_type": {"$first": "$vehicle_type"},
            "latitude":     {"$first": "$latitude"},
            "longitude":    {"$first": "$longitude"},
            "speed":        {"$first": "$speed"},
            "health_score": {"$first": "$health_score"},
            "driving_mode": {"$first": "$driving_mode"},
            "engine_temp":  {"$first": "$engine_temp"},
        }}
    ]
    try:
        results = list(collection.aggregate(pipeline))
    except Exception as e:
        # Fallback if 2dsphere index not yet built
        raise HTTPException(status_code=500, detail=f"Geospatial query error: {e}")

    return {
        "center":    {"lat": lat, "lon": lon},
        "radius_km": radius_km,
        "count":     len(results),
        "vehicles": [{
            "vehicle_id":   r["_id"],
            "vehicle_type": r.get("vehicle_type",""),
            "latitude":     r.get("latitude", 0),
            "longitude":    r.get("longitude", 0),
            "speed":        r.get("speed", 0),
            "health_score": r.get("health_score", 100),
            "driving_mode": r.get("driving_mode",""),
            "engine_temp":  r.get("engine_temp", 0),
        } for r in results]
    }


# ── Alerts ─────────────────────────────────────────────────
@app.get("/api/alerts")
def get_alerts(
    vehicle_id:      Optional[str] = None,
    severity:        Optional[str] = None,
    alert_type:      Optional[str] = None,
    unresolved_only: bool          = False,
    limit:           int           = Query(default=50, le=200)
):
    query = {}
    if vehicle_id:      query["vehicle_id"] = vehicle_id
    if severity:        query["severity"]   = severity
    if alert_type:      query["alert_type"] = alert_type
    if unresolved_only: query["resolved"]   = False
    cursor = alerts_col.find(query, sort=[("timestamp",-1)], limit=limit)
    return {"alerts": [serialize(d) for d in cursor]}


@app.get("/api/alerts/count")
def get_alert_count():
    critical = alerts_col.count_documents({"severity":"critical","resolved":False})
    warning  = alerts_col.count_documents({"severity":"warning", "resolved":False})
    return {"critical": critical, "warning": warning, "total": critical + warning}


@app.patch("/api/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: str):
    from bson import ObjectId
    try:
        r = alerts_col.update_one(
            {"_id": ObjectId(alert_id)},
            {"$set": {"resolved": True, "resolved_at": datetime.now(timezone.utc)}}
        )
        if r.matched_count == 0:
            raise HTTPException(status_code=404, detail="Alert not found")
        return {"status": "resolved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Aggregated tier data ───────────────────────────────────
@app.get("/api/telemetry/{vehicle_id}/{data_type}")
def get_aggregated(vehicle_id: str, data_type: str):
    valid = ["minute","hourly","daily","yearly"]
    if data_type not in valid:
        raise HTTPException(status_code=400, detail=f"data_type must be one of {valid}")
    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": data_type},
        sort=[("timestamp",-1)], limit=100
    )
    records = [serialize(d) for d in cursor]
    if not records:
        raise HTTPException(status_code=404, detail=f"No {data_type} data for {vehicle_id}")
    return {"vehicle_id": vehicle_id, "data_type": data_type,
            "total_records": len(records), "data": records}


# ── Analytics ──────────────────────────────────────────────
@app.get("/api/analytics/fleet-overview")
def get_fleet_analytics():
    pipeline = [
        {"$match": {"data_type":"raw"}},
        {"$sort": {"timestamp":-1}},
        {"$group": {
            "_id":                  "$vehicle_id",
            "vehicle_type":         {"$first": "$vehicle_type"},
            "speed":                {"$first": "$speed"},
            "health_score":         {"$first": "$health_score"},
            "driver_safety_score":  {"$first": "$driver_safety_score"},
            "fuel_level":           {"$first": "$fuel_level"},
            "engine_temp":          {"$first": "$engine_temp"},
            "maintenance_required": {"$first": "$maintenance_required"},
        }},
        {"$group": {
            "_id":               "$vehicle_type",
            "count":             {"$sum": 1},
            "avg_speed":         {"$avg": "$speed"},
            "avg_health":        {"$avg": "$health_score"},
            "avg_safety":        {"$avg": "$driver_safety_score"},
            "avg_fuel":          {"$avg": "$fuel_level"},
            "avg_temp":          {"$avg": "$engine_temp"},
            "maintenance_count": {"$sum": {"$cond": ["$maintenance_required",1,0]}},
        }}
    ]
    results = list(collection.aggregate(pipeline))
    return {"by_type": [{
        "vehicle_type":      r["_id"],
        "count":             r.get("count", 0),
        "avg_speed":         round(r.get("avg_speed",  0) or 0, 1),
        "avg_health":        round(r.get("avg_health", 0) or 0, 1),
        "avg_safety":        round(r.get("avg_safety", 0) or 0, 1),
        "avg_fuel":          round(r.get("avg_fuel",   0) or 0, 1),
        "avg_temp":          round(r.get("avg_temp",   0) or 0, 1),
        "maintenance_count": r.get("maintenance_count", 0),
    } for r in sorted(results, key=lambda x: x["_id"] or "")]}


@app.get("/api/analytics/maintenance-risk")
def get_maintenance_risk():
    pipeline = [
        {"$match": {"data_type":"raw"}},
        {"$sort": {"timestamp":-1}},
        {"$group": {
            "_id":                  "$vehicle_id",
            "vehicle_type":         {"$first": "$vehicle_type"},
            "health_score":         {"$first": "$health_score"},
            "oil_pressure":         {"$first": "$oil_pressure"},
            "engine_vibration":     {"$first": "$engine_vibration"},
            "maintenance_required": {"$first": "$maintenance_required"},
            "running_hours":        {"$first": "$running_hours"},
            "odometer":             {"$first": "$odometer"},
            "driver_safety_score":  {"$first": "$driver_safety_score"},
        }}
    ]
    results = list(collection.aggregate(pipeline))
    output  = []
    for r in results:
        hs   = r.get("health_score", 100) or 100
        risk = "CRITICAL" if hs<40 else ("HIGH" if hs<60 else ("MEDIUM" if hs<75 else "LOW"))
        output.append({
            "vehicle_id":           r["_id"],
            "vehicle_type":         r.get("vehicle_type",""),
            "health_score":         round(hs, 1),
            "oil_pressure":         round(r.get("oil_pressure",0) or 0, 1),
            "engine_vibration":     round(r.get("engine_vibration",0) or 0, 2),
            "maintenance_required": r.get("maintenance_required", False),
            "running_hours":        round(r.get("running_hours",0) or 0, 2),
            "odometer":             round(r.get("odometer",0) or 0, 0),
            "driver_safety_score":  round(r.get("driver_safety_score",100) or 100, 1),
            "risk_level":           risk,
        })
    output.sort(key=lambda x: x["health_score"])
    return {"total": len(output), "vehicles": output}


@app.get("/api/analytics/trends")
def get_fleet_trends(minutes: int = Query(default=30, ge=5, le=120)):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    pipeline = [
        {"$match": {"data_type":"raw","timestamp":{"$gte":since}}},
        {"$group": {
            "_id": {"minute": {"$dateToString": {"format":"%Y-%m-%dT%H:%M:00Z","date":"$timestamp"}}},
            "avg_health":  {"$avg":"$health_score"},
            "avg_safety":  {"$avg":"$driver_safety_score"},
            "avg_speed":   {"$avg":"$speed"},
            "avg_fuel":    {"$avg":"$fuel_level"},
            "avg_temp":    {"$avg":"$engine_temp"},
            "count":       {"$sum":1},
        }},
        {"$sort": {"_id.minute":1}}
    ]
    results = list(collection.aggregate(pipeline))
    return {"minutes_back": minutes, "trends": [{
        "timestamp":    r["_id"]["minute"],
        "avg_health":   round(r.get("avg_health",0) or 0, 1),
        "avg_safety":   round(r.get("avg_safety",0) or 0, 1),
        "avg_speed":    round(r.get("avg_speed", 0) or 0, 1),
        "avg_fuel":     round(r.get("avg_fuel",  0) or 0, 1),
        "avg_temp":     round(r.get("avg_temp",  0) or 0, 1),
        "record_count": r.get("count", 0),
    } for r in results]}


@app.get("/api/analytics/edge-stats")
def get_edge_stats():
    """
    Shows how many readings were suppressed by edge computing logic
    and the resulting bandwidth savings.
    """
    model_status = {
        vtype: f"trained on {len(training_buffer[vtype])} samples"
        for vtype in training_buffer
    }
    trained = list(isolation_models.keys())
    return {
        "edge_computing": edge_stats,
        "ml_models": {
            "trained_types":  trained,
            "pending_types":  {
                vtype: f"{len(training_buffer[vtype])}/{TRAIN_AFTER} samples"
                for vtype in training_buffer if vtype not in isolation_models
            },
            "train_threshold": TRAIN_AFTER,
            "features_used":   ANOMALY_FEATURES,
        },
        "websocket_connections": len(ws_manager.connections),
        "active_vehicles":       list(ws_manager.connections.keys()),
    }