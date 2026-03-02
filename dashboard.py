import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta

# ── Page Config ────────────────────────────────────────────
st.set_page_config(
    page_title="Vehicle Telemetry Dashboard",
    page_icon="🚗",
    layout="wide"
)

API_BASE = "http://localhost:8000"

# ── Dark Navy Theme ────────────────────────────────────────
st.markdown("""
<style>
.stApp {
    background-color: #0a0f1e;
    color: #e0e6f0;
}
[data-testid="stSidebar"] {
    background-color: #0d1428;
    border-right: 1px solid #1e2d4a;
}
[data-testid="stMetric"] {
    background-color: #111c35;
    border: 1px solid #1e3a5f;
    border-radius: 12px;
    padding: 16px;
}
[data-testid="stMetricLabel"] {
    color: #7a9cc4 !important;
    font-size: 13px !important;
}
[data-testid="stMetricValue"] {
    color: #00d4ff !important;
    font-size: 26px !important;
    font-weight: 700 !important;
}
.stButton > button {
    background: linear-gradient(135deg, #1a4a8a, #0066cc);
    color: white;
    border: none;
    border-radius: 10px;
    height: 3em;
    width: 100%;
    font-size: 15px;
    font-weight: 600;
    transition: all 0.2s ease;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #0066cc, #00aaff);
    transform: translateY(-1px);
}
.stTextInput > div > div > input,
.stSelectbox > div > div,
.stDateInput > div > div > input {
    background-color: #111c35 !important;
    color: #e0e6f0 !important;
    border: 1px solid #1e3a5f !important;
    border-radius: 8px !important;
}
.stTabs [data-baseweb="tab-list"] {
    background-color: #0d1428;
    border-radius: 10px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    color: #7a9cc4;
    font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background-color: #1a4a8a !important;
    color: white !important;
    border-radius: 8px;
}
[data-testid="stDataFrame"] {
    background-color: #111c35;
    border-radius: 10px;
}
hr { border-color: #1e2d4a; }
.dashboard-title {
    font-size: 38px;
    font-weight: 800;
    color: #00d4ff;
    letter-spacing: -0.5px;
}
.dashboard-subtitle {
    color: #7a9cc4;
    font-size: 15px;
    margin-top: -10px;
}
.status-online {
    background-color: #0d2e1a;
    color: #00ff88;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #00ff88;
}
.status-offline {
    background-color: #2e0d0d;
    color: #ff4444;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    border: 1px solid #ff4444;
}
</style>
""", unsafe_allow_html=True)


# ── Login ──────────────────────────────────────────────────
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='dashboard-title'>🚘 Vehicle Monitor</div>", unsafe_allow_html=True)
        st.markdown("<div class='dashboard-subtitle'>Secure access to fleet telemetry data</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        username = st.text_input("👤 Username")
        password = st.text_input("🔑 Password", type="password")
        if st.button("Login →"):
            if username == "admin" and password == "1234":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("❌ Invalid credentials")
    st.stop()


# ── Helper — format running hours ─────────────────────────
def format_running_hours(val):
    """Convert decimal running hours to hrs & mins display."""
    if val is None or val == "N/A":
        return "N/A"
    try:
        val = float(val)
        total_mins = int(val * 60)
        hrs  = total_mins // 60
        mins = total_mins % 60
        if hrs == 0:
            return f"{mins} min"
        return f"{hrs}h {mins}m"
    except:
        return str(val)


# ── Helper — display vehicle metrics ──────────────────────
def display_metrics(rec):
    c1, c2, c3 = st.columns(3)
    c1.metric("🚀 Speed",            f"{rec.get('speed', 'N/A')} km/h")
    c2.metric("⚙️ RPM",               f"{int(rec.get('rpm', rec.get('avg_rpm', 0)))} RPM" if isinstance(rec.get('rpm', rec.get('avg_rpm')), (int, float)) else "N/A")
    c3.metric("🌡️ Engine Temp",       f"{rec.get('temperature', rec.get('avg_temperature', 'N/A'))} °C")

    c4, c5, c6 = st.columns(3)
    c4.metric("⛽ Fuel Level",         f"{rec.get('fuel_level', rec.get('avg_fuel_level', 'N/A'))} %")
    c5.metric("🔋 Battery",            f"{rec.get('battery_level', rec.get('avg_battery_level', 'N/A'))} %")
    c6.metric("⏱️ Engine Run Time",    format_running_hours(rec.get('running_hours', rec.get('avg_running_hours'))))

    col_mode, col_time = st.columns(2)
    if rec.get("driving_mode"):
        col_mode.markdown(f"**Driving Mode:** `{rec['driving_mode'].upper()}`")
    if rec.get("timestamp"):
        col_time.caption(f"🕐 Recorded at: {rec['timestamp']}")


# ── Session state for past data toggle ────────────────────
if "show_past_picker" not in st.session_state:
    st.session_state.show_past_picker = False


# ── Main Dashboard ─────────────────────────────────────────
st.markdown("<div class='dashboard-title'>🚗 Vehicle Telemetry Dashboard</div>", unsafe_allow_html=True)
st.markdown("<div class='dashboard-subtitle'>Real-time fleet monitoring with hot-cold storage architecture</div>", unsafe_allow_html=True)
st.markdown("<br>", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["🔍  Vehicle Lookup", "🚘  Fleet Summary", "📈  Live Charts"])


# ── TAB 1 — Vehicle Lookup ─────────────────────────────────
with tab1:
    st.markdown("#### Search Vehicle")

    col1, col2 = st.columns(2)
    with col1:
        vehicle_id = st.text_input("Vehicle ID", placeholder="e.g. TRUCK-001, CAR-012, VAN-005")
    with col2:
        vehicle_type = st.selectbox("Vehicle Type", ["All", "TRUCK", "CAR", "VAN"])

    st.divider()

    # ── Two buttons side by side ───────────────────────────
    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button("📅 Fetch Past Vehicle Data", key="toggle_past"):
            st.session_state.show_past_picker = not st.session_state.show_past_picker
    with btn_col2:
        fetch_present = st.button("⚡ Present Time", key="present")

    # ── Date/Time picker — only visible after clicking past button
    if st.session_state.show_past_picker:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### 🕐 Select Date & Time")

        col3, col4 = st.columns(2)
        with col3:
            selected_date = st.date_input("Date")
        with col4:
            selected_time = st.time_input("Time")

        selected_dt     = datetime.combine(selected_date, selected_time)
        selected_dt_utc = selected_dt.replace(tzinfo=timezone.utc)
        now             = datetime.now(timezone.utc)
        diff            = now - selected_dt_utc

        # Storage layer detection
        if diff <= timedelta(hours=1):
            layer_label = "🔥 HOT — per-second data"
            layer       = "hot"
        elif diff <= timedelta(days=1):
            layer_label = "🌡️ WARM — per-minute data"
            layer       = "warm"
        elif diff <= timedelta(days=3):
            layer_label = "❄️ COLD — hourly data"
            layer       = "cold"
        elif diff <= timedelta(days=365):
            layer_label = "🧊 ARCHIVE — daily data"
            layer       = "archive"
        else:
            layer_label = "📦 PERMANENT — yearly data"
            layer       = "permanent"

        st.info(f"**Storage Layer:** {layer_label}")

        fetch_past = st.button("🔍 Search Past Data", key="fetch_past")

        if fetch_past:
            if not vehicle_id.strip():
                st.warning("Please enter a Vehicle ID")
            else:
                vid = vehicle_id.strip().upper()
                with st.spinner(f"Fetching past data for {vid}..."):
                    try:
                        if layer == "hot":
                            r = requests.get(f"{API_BASE}/api/telemetry/{vid}/latest", timeout=10)
                        else:
                            r = requests.get(
                                f"{API_BASE}/api/telemetry/{vid}/smart",
                                params={"selected_datetime": selected_dt_utc.isoformat()},
                                timeout=10
                            )

                        if r.status_code == 200:
                            result = r.json()

                            if "data" in result and isinstance(result["data"], list):
                                if not result["data"]:
                                    st.warning("No records found for this time range.")
                                    st.stop()
                                rec = result["data"][0]
                                st.success(f"✅ {result.get('total_records', 1)} records from **{result.get('storage_layer', layer_label)}**")
                            else:
                                rec = result

                            st.markdown("#### 📊 Past Data Reading")
                            display_metrics(rec)

                            if "data" in result and len(result["data"]) > 1:
                                st.markdown("#### 📋 All Records")
                                df = pd.DataFrame(result["data"])
                                df = df.drop(columns=["_id"], errors="ignore")
                                st.dataframe(df, use_container_width=True)

                        elif r.status_code == 404:
                            st.error(f"No data found for **{vid}**. Is the simulator running?")
                        else:
                            st.error(f"API error {r.status_code}: {r.text}")

                    except requests.exceptions.ConnectionError:
                        st.error("❌ Cannot connect to backend API.")
                    except Exception as e:
                        st.error(f"Error: {e}")

    # ── Present Time button ────────────────────────────────
    if fetch_present:
        if not vehicle_id.strip():
            st.warning("Please enter a Vehicle ID")
        else:
            vid = vehicle_id.strip().upper()
            with st.spinner(f"Fetching live data for {vid}..."):
                try:
                    r = requests.get(f"{API_BASE}/api/telemetry/{vid}/latest", timeout=10)

                    if r.status_code == 200:
                        rec = r.json()
                        st.success(f"⚡ Live reading for **{vid}**")
                        st.markdown("#### 📊 Present Time Reading")
                        display_metrics(rec)

                    elif r.status_code == 404:
                        st.error(f"No data found for **{vid}**. Is the simulator running?")
                    else:
                        st.error(f"API error {r.status_code}: {r.text}")

                except requests.exceptions.ConnectionError:
                    st.error("❌ Cannot connect to backend API.")
                except Exception as e:
                    st.error(f"Error: {e}")


# ── TAB 2 — Fleet Summary ──────────────────────────────────
with tab2:
    st.markdown("#### 🚘 All Active Vehicles")

    if st.button("🔄 Refresh Fleet", key="fleet"):
        with st.spinner("Loading fleet..."):
            try:
                r = requests.get(f"{API_BASE}/api/vehicles/summary", timeout=10)

                if r.status_code == 200:
                    result  = r.json()
                    vehicles = result["vehicles"]
                    st.success(f"✅ {result['total_vehicles']} active vehicles")

                    st.markdown("#### 📊 Fleet Averages")
                    df = pd.DataFrame(vehicles)

                    c1, c2, c3, c4, c5 = st.columns(5)
                    c1.metric("Avg Speed",        f"{df['speed'].mean():.1f} km/h")
                    c2.metric("Avg Engine Temp",  f"{df['temperature'].mean():.1f} °C")
                    c3.metric("Avg RPM",          f"{df['rpm'].mean():.0f} RPM")
                    c4.metric("Avg Fuel",         f"{df['fuel_level'].mean():.1f} %")
                    c5.metric("Avg Battery",      f"{df['battery_level'].mean():.1f} %")

                    st.divider()

                    st.markdown("#### 📋 Vehicle List")
                    display_df = df[["vehicle_id", "speed", "rpm", "temperature",
                                     "fuel_level", "battery_level", "running_hours",
                                     "driving_mode", "last_seen"]].copy()

                    # Format running hours nicely
                    display_df["running_hours"] = display_df["running_hours"].apply(format_running_hours)

                    display_df.columns = ["Vehicle ID", "Speed (km/h)", "RPM",
                                          "Engine Temp (°C)", "Fuel (%)", "Battery (%)",
                                          "Engine Run Time", "Mode", "Last Seen"]
                    st.dataframe(display_df, use_container_width=True)

                else:
                    st.error(f"API error: {r.status_code}")

            except requests.exceptions.ConnectionError:
                st.error("❌ Cannot connect to backend API.")
            except Exception as e:
                st.error(f"Error: {e}")


# ── TAB 3 — Live Charts ────────────────────────────────────
with tab3:
    st.markdown("#### 📈 Telemetry Charts")

    col1, col2 = st.columns(2)
    with col1:
        chart_vid  = st.text_input("Vehicle ID", placeholder="e.g. TRUCK-001", key="chart_vid")
    with col2:
        chart_mins = st.slider("Minutes back", 1, 60, 10)

    if st.button("📈 Load Charts", key="charts"):
        if not chart_vid.strip():
            st.warning("Please enter a Vehicle ID")
        else:
            vid = chart_vid.strip().upper()
            with st.spinner("Loading chart data..."):
                try:
                    r = requests.get(
                        f"{API_BASE}/api/telemetry/{vid}",
                        params={"minutes": chart_mins},
                        timeout=10
                    )

                    if r.status_code == 200:
                        result = r.json()
                        df = pd.DataFrame(result["data"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp")

                        st.success(f"✅ {result['total_records']} records loaded for {vid}")

                        st.markdown("**🚀 Speed (km/h)**")
                        st.line_chart(df.set_index("timestamp")[["speed"]])

                        st.markdown("**🌡️ Engine Temperature (°C)**")
                        st.line_chart(df.set_index("timestamp")[["temperature"]])

                        st.markdown("**⚙️ RPM**")
                        st.line_chart(df.set_index("timestamp")[["rpm"]])

                        st.markdown("**⛽ Fuel (%) & 🔋 Battery (%)**")
                        st.line_chart(df.set_index("timestamp")[["fuel_level", "battery_level"]])

                        st.markdown("**⏱️ Engine Run Time (hours)**")
                        st.line_chart(df.set_index("timestamp")[["running_hours"]])

                    elif r.status_code == 404:
                        st.error(f"No data found for **{vid}**")
                    else:
                        st.error(f"API error {r.status_code}")

                except requests.exceptions.ConnectionError:
                    st.error("❌ Cannot connect to backend API.")
                except Exception as e:
                    st.error(f"Error: {e}")


# ── Sidebar ────────────────────────────────────────────────
st.sidebar.markdown("### 🚗 Fleet Monitor")
st.sidebar.markdown("---")

try:
    r = requests.get(f"{API_BASE}/", timeout=3)
    if r.status_code == 200:
        st.sidebar.markdown("<span class='status-online'>● API Online</span>", unsafe_allow_html=True)
    else:
        st.sidebar.markdown("<span class='status-offline'>● API Issue</span>", unsafe_allow_html=True)
except:
    st.sidebar.markdown("<span class='status-offline'>● API Offline</span>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Storage Architecture**

🔥 Hot → per-second *(last 1hr)*
🌡️ Warm → per-minute *(last 1 day)*
❄️ Cold → hourly *(last 3 days)*
🧊 Archive → daily *(last 1 year)*
📦 Permanent → yearly *(forever)*
""")

st.sidebar.markdown("---")
st.sidebar.markdown("""
**Physics Model**

- Speed → correlated RPM
- Hours running → rising engine temp
- Speed + load → fuel consumption
- Time → battery drain
""")

st.sidebar.markdown("---")
if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.rerun()