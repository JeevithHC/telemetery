"""
Vehicle Telemetry Simulator — Realistic Physics Model
------------------------------------------------------
Each vehicle tracks:
- running_hours: how long it has been running (increments every second)
- speed:         realistic acceleration/deceleration over time
- rpm:           directly correlated with speed + vehicle type
- temperature:   rises with running hours AND speed (cools when idle)
- fuel_level:    decreases based on speed + running load
- battery_level: slow drain over time
- timestamp:     UTC timestamp of each reading
"""

import requests
import random
import time
import threading
from datetime import datetime, timezone

# ── Config ─────────────────────────────────────────────────
API_URL       = "http://localhost:8000/api/telemetry"
SEND_INTERVAL = 1  # seconds between readings

VEHICLES = [f"TRUCK-{i:03d}" for i in range(1, 51)] + \
           [f"CAR-{i:03d}"   for i in range(1, 26)] + \
           [f"VAN-{i:03d}"   for i in range(1, 26)]

random.shuffle(VEHICLES)
# ──────────────────────────────────────────────────────────


# ── Vehicle Type Profiles ──────────────────────────────────
PROFILES = {
    "TRUCK": {
        "max_speed":       100,   # km/h
        "idle_rpm":        750,
        "max_rpm":         2500,
        "base_temp":       75,    # °C when cold
        "max_temp":        115,   # °C at full load for hours
        "temp_per_hour":   8,     # °C added per running hour
        "temp_per_speed":  0.15,  # °C added per km/h
        "fuel_capacity":   300,   # litres
        "fuel_per_hour":   120,   # scaled up for demo visibility
        "battery_start":   100,
        "battery_drain":   0.02   # % per second — visible in ~83 mins
    },
    "CAR": {
        "max_speed":       140,
        "idle_rpm":        700,
        "max_rpm":         4500,
        "base_temp":       70,
        "max_temp":        105,
        "temp_per_hour":   6,
        "temp_per_speed":  0.10,
        "fuel_capacity":   50,
        "fuel_per_hour":   60,
        "battery_start":   100,
        "battery_drain":   0.015
    },
    "VAN": {
        "max_speed":       120,
        "idle_rpm":        750,
        "max_rpm":         3500,
        "base_temp":       72,
        "max_temp":        110,
        "temp_per_hour":   7,
        "temp_per_speed":  0.12,
        "fuel_capacity":   80,
        "fuel_per_hour":   90,
        "battery_start":   100,
        "battery_drain":   0.018
    }
}


def get_profile(vehicle_id: str) -> dict:
    if "TRUCK" in vehicle_id:
        return PROFILES["TRUCK"]
    elif "CAR" in vehicle_id:
        return PROFILES["CAR"]
    else:
        return PROFILES["VAN"]


def simulate_vehicle(vehicle_id: str):
    """Simulate a single vehicle with realistic correlated telemetry."""

    profile = get_profile(vehicle_id)

    # ── Initial State ──────────────────────────────────────
    running_seconds = 0
    speed           = 0.0
    fuel_level      = float(profile["fuel_capacity"])
    battery_level   = float(profile["battery_start"])
    temperature     = 25.0  # starts at ambient (cold engine)

    # Each vehicle starts with a random driving mode
    mode              = random.choice(["city", "highway", "idle"])
    mode_duration     = random.randint(30, 120)  # seconds to stay in this mode
    mode_timer        = 0
    target_speed      = 0.0

    print(f"[START] {vehicle_id} — mode: {mode}")

    while True:
        running_hours = running_seconds / 3600.0
        timestamp     = datetime.now(timezone.utc)

        max_speed = profile["max_speed"]

        # ── Mode switching — stay in mode for realistic duration ──
        mode_timer += 1
        if mode_timer >= mode_duration:
            # Pick next mode with weighted probability
            mode = random.choices(
                ["city", "highway", "idle", "braking"],
                weights=[40, 35, 15, 10]
            )[0]
            mode_timer    = 0
            mode_duration = random.randint(30, 120)  # next mode lasts 30–120 seconds

        # ── Set target speed based on mode ─────────────────
        if mode == "highway":
            # Pick a consistent highway cruise speed for this phase
            if mode_timer == 0:
                target_speed = random.uniform(max_speed * 0.70, max_speed * 0.95)
        elif mode == "city":
            # Occasionally vary city speed (stop-start traffic)
            if mode_timer == 0 or mode_timer % 15 == 0:
                target_speed = random.uniform(10, max_speed * 0.45)
        elif mode == "idle":
            target_speed = 0
        elif mode == "braking":
            target_speed = max(0, speed - random.uniform(3, 10))

        # ── Smooth acceleration/deceleration ───────────────
        # Gradual change toward target — no instant jumps
        if speed < target_speed:
            accel = random.uniform(0.5, 2.0)  # gentle acceleration
            speed = min(speed + accel, target_speed)
        elif speed > target_speed:
            decel = random.uniform(1.0, 4.0)  # braking
            speed = max(speed - decel, target_speed)

        speed = round(max(0.0, min(speed, max_speed)), 2)

        # ── RPM — directly tracks speed smoothly ───────────
        idle_rpm = profile["idle_rpm"]
        max_rpm  = profile["max_rpm"]

        if speed == 0:
            # Idling — small fluctuation around idle RPM
            rpm = round(random.uniform(idle_rpm - 50, idle_rpm + 100), 0)
        else:
            speed_ratio = speed / max_speed
            # RPM rises proportionally with speed
            base_rpm = idle_rpm + (max_rpm - idle_rpm) * speed_ratio
            # Small variance for gear changes (±100 RPM max)
            rpm = round(base_rpm + random.uniform(-100, 100), 0)
            rpm = max(idle_rpm, min(rpm, max_rpm))

        # ── Temperature — cold start + hours + speed ───────
        AMBIENT_TEMP = 25.0
        hour_heat    = profile["temp_per_hour"] * running_hours
        speed_heat   = profile["temp_per_speed"] * speed
        target_temp  = AMBIENT_TEMP + hour_heat + speed_heat

        # Only add noise after engine is warmed up
        if running_hours > 0.05:
            target_temp += random.uniform(-1.0, 1.0)

        # Cap at max operating temp
        target_temp = min(target_temp, profile["max_temp"])

        # Temperature moves gradually toward target (thermal inertia)
        if temperature < target_temp:
            temperature += random.uniform(0.1, 0.5)
        elif temperature > target_temp:
            temperature -= random.uniform(0.05, 0.2)

        # Never go below ambient
        temperature = round(max(AMBIENT_TEMP, min(temperature, profile["max_temp"])), 2)

        # ── Fuel — decreases based on speed and running time
        fuel_consumption_per_second = (profile["fuel_per_hour"] / 3600) * (0.3 + 0.7 * (speed / max_speed))
        fuel_level = max(0, fuel_level - fuel_consumption_per_second)
        fuel_level = round(fuel_level, 3)

        # Convert to percentage
        fuel_pct = round((fuel_level / profile["fuel_capacity"]) * 100, 2)

        # ── Battery — slow drain over time ─────────────────
        battery_level = max(0, battery_level - profile["battery_drain"])
        battery_level = round(battery_level, 3)

        # ── Build payload ──────────────────────────────────
        payload = {
            "vehicle_id":     vehicle_id,
            "timestamp":      timestamp.isoformat(),
            "running_hours":  round(running_hours, 4),
            "speed":          speed,
            "rpm":            rpm,
            "temperature":    temperature,
            "fuel_level":     fuel_pct,
            "battery_level":  battery_level,
            "driving_mode":   mode
        }

        # ── Send to API ────────────────────────────────────
        try:
            response = requests.post(API_URL, json=payload, timeout=5)

            if response.status_code == 201:
                print(f"[OK] {vehicle_id} | "
                      f"{running_hours:.2f}h | "
                      f"speed={speed} km/h | "
                      f"rpm={rpm:.0f} | "
                      f"temp={temperature}°C | "
                      f"fuel={fuel_pct}% | "
                      f"mode={mode}")
            else:
                print(f"[WARN] {vehicle_id} → {response.status_code}")

        except requests.exceptions.ConnectionError:
            print(f"[ERROR] {vehicle_id} → Cannot connect to API.")
        except requests.exceptions.Timeout:
            print(f"[ERROR] {vehicle_id} → Timeout.")

        running_seconds += SEND_INTERVAL
        time.sleep(SEND_INTERVAL)


def main():
    print("=" * 60)
    print("   Vehicle Telemetry Simulator — Realistic Physics Model")
    print(f"   {len(VEHICLES)} vehicles | {SEND_INTERVAL}s interval")
    print("=" * 60)
    print("Press CTRL+C to stop.\n")

    threads = []
    for vehicle_id in VEHICLES:
        t = threading.Thread(target=simulate_vehicle, args=(vehicle_id,), daemon=True)
        threads.append(t)
        t.start()
        time.sleep(0.05)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOP] Simulator shut down.")


if __name__ == "__main__":
    main()