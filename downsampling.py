"""
Downsampling Script — 4 Level Aggregation
------------------------------------------
raw → minute → hourly → daily → yearly

Cleanup:
- raw:    delete after 1 hour
- minute: delete after 1 day
- hourly: delete after 3 days
- daily:  delete after 1 year
"""

from database import collection
from datetime import datetime, timezone, timedelta


def avg(records, field):
    vals = [r.get(field, 0) for r in records if r.get(field) is not None]
    return round(sum(vals) / len(vals), 3) if vals else 0


def aggregate(source_type, target_type, period, label):
    print(f"\n  [{label}] {source_type} → {target_type}...")
    now          = datetime.now(timezone.utc)
    period_start = now - period
    vehicles     = collection.distinct("vehicle_id", {"data_type": source_type})

    for vehicle_id in vehicles:
        records = list(collection.find({
            "vehicle_id": vehicle_id,
            "data_type":  source_type,
            "timestamp":  {"$gte": period_start, "$lte": now}
        }))

        if not records:
            continue

        summary = {
            "vehicle_id":        vehicle_id,
            "timestamp":         now,
            "data_type":         target_type,
            "avg_speed":         avg(records, "speed"),
            "avg_rpm":           avg(records, "rpm"),
            "avg_temperature":   avg(records, "temperature"),
            "avg_fuel_level":    avg(records, "fuel_level"),
            "avg_battery_level": avg(records, "battery_level"),
            "avg_running_hours": avg(records, "running_hours"),
            "record_count":      len(records),
            "period_start":      period_start,
            "period_end":        now
        }

        collection.insert_one(summary)
        print(f"    ✅ {vehicle_id} → saved ({len(records)} records averaged)")


def cleanup(data_type, older_than):
    cutoff  = datetime.now(timezone.utc) - older_than
    deleted = collection.delete_many({"data_type": data_type, "timestamp": {"$lt": cutoff}})
    if deleted.deleted_count > 0:
        print(f"  🗑️  Deleted {deleted.deleted_count} {data_type} records")


def downsample():
    print(f"\n{'='*50}")
    print(f"[{datetime.now()}] Running downsampling...")

    aggregate("raw",    "minute", timedelta(minutes=1), "1/4")
    aggregate("minute", "hourly", timedelta(hours=1),   "2/4")
    aggregate("hourly", "daily",  timedelta(days=1),    "3/4")
    aggregate("daily",  "yearly", timedelta(days=365),  "4/4")

    print("\n  Cleaning up...")
    cleanup("raw",    timedelta(hours=1))
    cleanup("minute", timedelta(days=1))
    cleanup("hourly", timedelta(days=3))
    cleanup("daily",  timedelta(days=365))

    print(f"\n[{datetime.now()}] Done.")

if __name__ == "__main__":
    downsample()