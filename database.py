"""
database.py — MongoDB + Redis connection layer
===============================================
New in v3:
  - 2dsphere geospatial index → enables radius-based vehicle queries
  - Redis with graceful fallback if not running
"""

from pymongo import MongoClient, ASCENDING, DESCENDING
from dotenv import load_dotenv
import redis
import os

load_dotenv()

# ── MongoDB ────────────────────────────────────────────────
MONGO_URI       = os.getenv("MONGO_URI",       "mongodb://localhost:27017/")
DB_NAME         = os.getenv("DB_NAME",          "vehicle_telemetry_v2")
COLLECTION_NAME = os.getenv("COLLECTION_NAME",  "telemetry")

mongo_client = MongoClient(MONGO_URI)
db           = mongo_client[DB_NAME]
collection   = db[COLLECTION_NAME]

# ── Standard indexes ───────────────────────────────────────
collection.create_index([("vehicle_id", ASCENDING), ("timestamp", DESCENDING)])
collection.create_index([("data_type",  ASCENDING), ("timestamp", DESCENDING)])
collection.create_index([("vehicle_id", ASCENDING), ("data_type", ASCENDING), ("timestamp", DESCENDING)])

# ── Geospatial 2dsphere index ──────────────────────────────
# Stores coordinates as GeoJSON Point { type:"Point", coordinates:[lon,lat] }
# Enables: find all vehicles within N km of any GPS point
try:
    collection.create_index([("location", "2dsphere")])
except Exception:
    pass   # index may already exist

# ── Alerts ─────────────────────────────────────────────────
alerts_col = db["telemetry_alerts"]
alerts_col.create_index([("vehicle_id", ASCENDING), ("timestamp", DESCENDING)])
alerts_col.create_index([("severity",   ASCENDING)])
alerts_col.create_index([("resolved",   ASCENDING)])
alerts_col.create_index([("alert_type", ASCENDING)])

# ── Redis ──────────────────────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

try:
    redis_client = redis.Redis(
        host=REDIS_HOST, port=REDIS_PORT,
        decode_responses=True, socket_connect_timeout=2
    )
    redis_client.ping()
    REDIS_OK = True
    print(f"✅ MongoDB  → {DB_NAME}")
    print(f"✅ Redis    → {REDIS_HOST}:{REDIS_PORT}")
except Exception:
    REDIS_OK = False
    print(f"✅ MongoDB  → {DB_NAME}")
    print("⚠️  Redis unavailable → MongoDB fallback active")

    class FakeRedis:
        def get(self, k):         return None
        def setex(self, *a, **k): pass
        def ping(self):           return False

    redis_client = FakeRedis()