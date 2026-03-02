from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from datetime import datetime, timezone, timedelta
from typing import Optional
from database import collection

app = FastAPI(
    title="Vehicle Telemetry API",
    description="Realistic vehicle telemetry with 5-tier hot-cold storage",
    version="3.0.0"
)


# ── Data Model ─────────────────────────────────────────────
class TelemetryInput(BaseModel):
    vehicle_id:    str
    timestamp:     Optional[datetime] = None
    running_hours: float = Field(..., ge=0,    description="Hours vehicle has been running")
    speed:         float = Field(..., ge=0,    le=300,  description="Speed in km/h")
    rpm:           float = Field(..., ge=0,    le=8000, description="Engine RPM")
    temperature:   float = Field(..., ge=0,    le=200,  description="Engine temp in Celsius")
    fuel_level:    float = Field(..., ge=0,    le=100,  description="Fuel level percentage")
    battery_level: float = Field(..., ge=0,    le=100,  description="Battery percentage")
    driving_mode:  str   = Field(default="unknown", description="city/highway/idle/braking")


# ── Helper ─────────────────────────────────────────────────
def serialize(doc) -> dict:
    doc["_id"] = str(doc["_id"])
    for field in ["timestamp", "period_start", "period_end"]:
        if isinstance(doc.get(field), datetime):
            doc[field] = doc[field].isoformat()
    return doc


def get_storage_layer(selected_datetime: datetime):
    now = datetime.now(timezone.utc)
    if selected_datetime.tzinfo is None:
        selected_datetime = selected_datetime.replace(tzinfo=timezone.utc)
    diff = now - selected_datetime

    if diff <= timedelta(hours=1):
        return "hot",       "raw",    "🔥 HOT STORAGE (per-second data)"
    elif diff <= timedelta(days=1):
        return "warm",      "minute", "🌡️ WARM STORAGE (per-minute data)"
    elif diff <= timedelta(days=3):
        return "cold",      "hourly", "❄️ COLD STORAGE (hourly data)"
    elif diff <= timedelta(days=365):
        return "archive",   "daily",  "🧊 ARCHIVE STORAGE (daily data)"
    else:
        return "permanent", "yearly", "📦 PERMANENT STORAGE (yearly data)"


# ── Routes ─────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "Vehicle Telemetry API is running 🚗"}


# POST — ingest telemetry
@app.post("/api/telemetry", status_code=201)
def receive_telemetry(data: TelemetryInput):
    doc = {
        "vehicle_id":    data.vehicle_id,
        "timestamp":     data.timestamp or datetime.now(timezone.utc),
        "running_hours": data.running_hours,
        "speed":         data.speed,
        "rpm":           data.rpm,
        "temperature":   data.temperature,
        "fuel_level":    data.fuel_level,
        "battery_level": data.battery_level,
        "driving_mode":  data.driving_mode,
        "data_type":     "raw"
    }
    result = collection.insert_one(doc)
    return {"status": "success", "id": str(result.inserted_id)}


# GET — smart retrieval by datetime (auto picks storage layer)
@app.get("/api/telemetry/{vehicle_id}/smart")
def get_smart(
    vehicle_id: str,
    selected_datetime: str = Query(..., description="ISO datetime e.g. 2026-03-01T10:00:00")
):
    try:
        dt = datetime.fromisoformat(selected_datetime)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format.")

    _, data_type, label = get_storage_layer(dt)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": data_type, "timestamp": {"$gte": dt, "$lte": now}},
        sort=[("timestamp", -1)],
        limit=100
    )
    records = [serialize(doc) for doc in cursor]

    return {
        "vehicle_id":    vehicle_id,
        "storage_layer": label,
        "data_type":     data_type,
        "total_records": len(records),
        "data":          records
    }


# GET — recent raw data
@app.get("/api/telemetry/{vehicle_id}")
def get_telemetry(
    vehicle_id: str,
    minutes: int = Query(default=10, ge=1, le=1440)
):
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": "raw", "timestamp": {"$gte": since}},
        sort=[("timestamp", -1)]
    )
    records = [serialize(doc) for doc in cursor]
    if not records:
        raise HTTPException(status_code=404, detail=f"No data for {vehicle_id} in last {minutes} mins")
    return {"vehicle_id": vehicle_id, "minutes_back": minutes, "total_records": len(records), "data": records}


# GET — latest reading
@app.get("/api/telemetry/{vehicle_id}/latest")
def get_latest(vehicle_id: str):
    doc = collection.find_one(
        {"vehicle_id": vehicle_id, "data_type": "raw"},
        sort=[("timestamp", -1)]
    )
    if not doc:
        raise HTTPException(status_code=404, detail=f"No data for {vehicle_id}")
    return serialize(doc)


# GET — fleet summary
@app.get("/api/vehicles/summary")
def get_summary():
    pipeline = [
        {"$match": {"data_type": "raw"}},
        {"$sort": {"timestamp": -1}},
        {"$group": {
            "_id":           "$vehicle_id",
            "speed":         {"$first": "$speed"},
            "temperature":   {"$first": "$temperature"},
            "rpm":           {"$first": "$rpm"},
            "fuel_level":    {"$first": "$fuel_level"},
            "battery_level": {"$first": "$battery_level"},
            "running_hours": {"$first": "$running_hours"},
            "driving_mode":  {"$first": "$driving_mode"},
            "last_seen":     {"$first": "$timestamp"}
        }}
    ]
    results = list(collection.aggregate(pipeline))
    return {
        "total_vehicles": len(results),
        "vehicles": [
            {
                "vehicle_id":    r["_id"],
                "speed":         r["speed"],
                "temperature":   r["temperature"],
                "rpm":           r["rpm"],
                "fuel_level":    r["fuel_level"],
                "battery_level": r["battery_level"],
                "running_hours": r["running_hours"],
                "driving_mode":  r["driving_mode"],
                "last_seen":     r["last_seen"]
            }
            for r in results
        ]
    }


# GET — aggregated data by type
@app.get("/api/telemetry/{vehicle_id}/{data_type}")
def get_aggregated(vehicle_id: str, data_type: str):
    valid = ["minute", "hourly", "daily", "yearly"]
    if data_type not in valid:
        raise HTTPException(status_code=400, detail=f"data_type must be one of {valid}")

    cursor = collection.find(
        {"vehicle_id": vehicle_id, "data_type": data_type},
        sort=[("timestamp", -1)],
        limit=100
    )
    records = [serialize(doc) for doc in cursor]
    if not records:
        raise HTTPException(status_code=404, detail=f"No {data_type} data for {vehicle_id}")
    return {"vehicle_id": vehicle_id, "data_type": data_type, "total_records": len(records), "data": records}