"""
downsampling.py — 4-Level Aggregation Pipeline
================================================
Compresses older data to save storage and keep queries fast.

Tiers
-----
raw     -> minute  (every 1 min)
minute  -> hourly  (every 1 hr)
hourly  -> daily   (every 1 day)
daily   -> yearly  (every 1 year)

Cleanup after aggregation
--------------------------
raw    records older than 1 hour  -> deleted
minute records older than 1 day   -> deleted
hourly records older than 3 days  -> deleted
daily  records older than 1 year  -> deleted

Windows usage
-------------
  Run manually   :  python downsampling.py
  Run via Task Scheduler (optional):
    Action -> Start a program
    Program : python
    Arguments: C:\\path\\to\\downsampling.py
    Trigger : Every 1 hour
"""

from database import collection
from datetime import datetime, timezone, timedelta


def avg(records, field):
    vals = [r[field] for r in records if isinstance(r.get(field), (int, float))]
    return round(sum(vals) / len(vals), 3) if vals else 0


def aggregate(source_type, target_type, period, label):
    print(f"\n  [{label}] {source_type} -> {target_type}...")
    now      = datetime.now(timezone.utc)
    since    = now - period
    vehicles = collection.distinct("vehicle_id", {"data_type": source_type})

    inserted = 0
    for vid in vehicles:
        records = list(collection.find({
            "vehicle_id": vid,
            "data_type":  source_type,
            "timestamp":  {"$gte": since, "$lte": now}
        }))
        if not records:
            continue

        vtype   = records[0].get("vehicle_type", "")
        summary = {
            "vehicle_id":              vid,
            "vehicle_type":            vtype,
            "timestamp":               now,
            "data_type":               target_type,
            "period_start":            since,
            "period_end":              now,
            "record_count":            len(records),
            # Core
            "avg_speed":               avg(records, "speed"),
            "avg_rpm":                 avg(records, "rpm"),
            "avg_running_hours":       avg(records, "running_hours"),
            # Thermal
            "avg_engine_temp":         avg(records, "engine_temp"),
            "avg_coolant_temp":        avg(records, "coolant_temp"),
            # Engine Health
            "avg_oil_pressure":        avg(records, "oil_pressure"),
            "avg_engine_vibration":    avg(records, "engine_vibration"),
            # Driver
            "avg_brake_pressure":      avg(records, "brake_pressure"),
            "avg_accelerator_pct":     avg(records, "accelerator_pct"),
            "avg_clutch_shifts":       avg(records, "clutch_shifts_per_min"),
            # Resources
            "avg_fuel_level":          avg(records, "fuel_level"),
            "avg_battery_level":       avg(records, "battery_level"),
            # Load
            "avg_load_weight_pct":     avg(records, "load_weight_pct"),
            # Derived Scores
            "avg_health_score":        avg(records, "health_score"),
            "avg_driver_safety_score": avg(records, "driver_safety_score"),
            # Last known GPS
            "latitude":  records[0].get("latitude", 0),
            "longitude": records[0].get("longitude", 0),
        }
        collection.insert_one(summary)
        inserted += 1

    print(f"      -> {inserted} vehicles aggregated into {target_type}")


def cleanup(data_type, older_than):
    cutoff  = datetime.now(timezone.utc) - older_than
    deleted = collection.delete_many({"data_type": data_type, "timestamp": {"$lt": cutoff}})
    if deleted.deleted_count > 0:
        print(f"  Cleaned {deleted.deleted_count} old {data_type} records")


def downsample():
    print(f"\n{'='*55}")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running downsampling pipeline...")
    print("="*55)

    # 4 aggregation passes
    aggregate("raw",    "minute", timedelta(minutes=1), "Pass 1/4")
    aggregate("minute", "hourly", timedelta(hours=1),   "Pass 2/4")
    aggregate("hourly", "daily",  timedelta(days=1),    "Pass 3/4")
    aggregate("daily",  "yearly", timedelta(days=365),  "Pass 4/4")

    # Cleanup old records
    print("\n  Running cleanup...")
    cleanup("raw",    timedelta(hours=1))
    cleanup("minute", timedelta(days=1))
    cleanup("hourly", timedelta(days=3))
    cleanup("daily",  timedelta(days=365))

    print(f"\n  Done — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    downsample()
