"""
dashboard.py — Vehicle Telemetry Dashboard v2
==============================================
Login    : admin / 1234
Tabs     :
  1. Vehicle Lookup    — Present Time + Past Data + PDF Export
  2. Fleet Summary     — Health Matrix + Predictive Maintenance + Fuel Cost Calculator
  3. Live Charts       — 6 chart groups
  4. Fleet Map         — Folium map, Chennai, color-coded health
  5. Alerts            — Real-time alert feed with filters
  6. Fleet Analytics   — Trends + Type Comparison + Risk Ranking

Windows  : streamlit run dashboard.py
"""

import io
import streamlit as st
import requests
import pandas as pd
import folium
from streamlit_folium import st_folium
from datetime import datetime, timezone, timedelta

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                 Table, TableStyle, HRFlowable)

# ── Page config ────────────────────────────────────────────
st.set_page_config(page_title="Fleet Telemetry v2", page_icon="🚗", layout="wide")
API_BASE = "http://localhost:8000"

# ── Theme ──────────────────────────────────────────────────
st.markdown("""<style>
.stApp{background-color:#0a0f1e;color:#e0e6f0}
[data-testid="stSidebar"]{background-color:#0d1428;border-right:1px solid #1e2d4a}
[data-testid="stMetric"]{background-color:#111c35;border:1px solid #1e3a5f;border-radius:12px;padding:16px}
[data-testid="stMetricLabel"]{color:#7a9cc4!important;font-size:12px!important}
[data-testid="stMetricValue"]{color:#00d4ff!important;font-size:22px!important;font-weight:700!important}
.stButton>button{background:linear-gradient(135deg,#1a4a8a,#0066cc);color:white;border:none;border-radius:10px;height:3em;width:100%;font-size:14px;font-weight:600}
.stButton>button:hover{background:linear-gradient(135deg,#0066cc,#00aaff)}
.stTextInput>div>div>input,.stSelectbox>div>div{background-color:#111c35!important;color:#e0e6f0!important;border:1px solid #1e3a5f!important;border-radius:8px!important}
.stTabs [data-baseweb="tab-list"]{background-color:#0d1428;border-radius:10px;padding:4px}
.stTabs [data-baseweb="tab"]{color:#7a9cc4;font-weight:600}
.stTabs [aria-selected="true"]{background-color:#1a4a8a!important;color:white!important;border-radius:8px}
[data-testid="stDataFrame"]{background-color:#111c35;border-radius:10px}
hr{border-color:#1e2d4a}
.dash-title{font-size:34px;font-weight:800;color:#00d4ff}
.dash-sub{color:#7a9cc4;font-size:14px}
.alert-critical{background:#2e0d0d;border-left:4px solid #ff4444;border-radius:8px;padding:12px 16px;margin-bottom:8px;color:#ffaaaa}
.alert-warning{background:#2e1f0d;border-left:4px solid #ffaa00;border-radius:8px;padding:12px 16px;margin-bottom:8px;color:#ffd580}
.bell-badge{background:#ff4444;color:white;border-radius:50%;padding:2px 8px;font-size:12px;font-weight:700;margin-left:4px}
.status-online{background:#0d2e1a;color:#00ff88;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid #00ff88}
.status-offline{background:#2e0d0d;color:#ff4444;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:600;border:1px solid #ff4444}
.maint-crit{background:#2e0d0d;border:1px solid #ff4444;border-radius:10px;padding:12px;margin:4px}
.maint-high{background:#2e1a0d;border:1px solid #ff7700;border-radius:10px;padding:12px;margin:4px}
.maint-med{background:#2e250d;border:1px solid #ffcc00;border-radius:10px;padding:12px;margin:4px}
</style>""", unsafe_allow_html=True)

# ── Session state ──────────────────────────────────────────
if "logged_in"    not in st.session_state: st.session_state.logged_in    = False
if "show_past"    not in st.session_state: st.session_state.show_past    = False
if "fleet_data"   not in st.session_state: st.session_state.fleet_data   = None
if "fleet_df"     not in st.session_state: st.session_state.fleet_df     = None
if "map_vehicles" not in st.session_state: st.session_state.map_vehicles = None
if "fuel_results" not in st.session_state: st.session_state.fuel_results = None
if "live_rec"     not in st.session_state: st.session_state.live_rec     = None
if "live_vid"     not in st.session_state: st.session_state.live_vid     = None

# ── Login ──────────────────────────────────────────────────
if not st.session_state.logged_in:
    st.markdown("<br><br>", unsafe_allow_html=True)
    _, c, _ = st.columns([1, 2, 1])
    with c:
        st.markdown("<div class='dash-title'>🚘 Fleet Monitor v2</div>", unsafe_allow_html=True)
        st.markdown("<div class='dash-sub'>Real-time IoT Vehicle Telemetry System</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        u = st.text_input("👤 Username")
        p = st.text_input("🔑 Password", type="password")
        if st.button("Login →"):
            if u == "admin" and p == "1234":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("❌ Invalid credentials")
    st.stop()


# ════════════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════════════

def fmt_hours(val):
    try:
        val = float(val)
        m   = int(val * 60)
        h, mn = divmod(m, 60)
        return f"{h}h {mn}m" if h > 0 else f"{mn} min"
    except:
        return str(val)


@st.cache_data(ttl=10)
def get_alert_counts():
    try:
        r = requests.get(f"{API_BASE}/api/alerts/count", timeout=3)
        return r.json() if r.status_code == 200 else {"critical": 0, "warning": 0, "total": 0}
    except:
        return {"critical": 0, "warning": 0, "total": 0}


def display_metrics(rec):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🚀 Speed",       f"{rec.get('speed','N/A')} km/h")
    c2.metric("⚙️ RPM",          f"{int(rec.get('rpm',0))} RPM" if isinstance(rec.get('rpm'),(int,float)) else "N/A")
    c3.metric("🌡️ Engine Temp",  f"{rec.get('engine_temp','N/A')} C")
    c4.metric("💧 Coolant",      f"{rec.get('coolant_temp','N/A')} C")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("⛽ Fuel",         f"{rec.get('fuel_level','N/A')} %")
    c6.metric("🔋 Battery",      f"{rec.get('battery_level','N/A')} %")
    c7.metric("🛢️ Oil Pressure", f"{rec.get('oil_pressure','N/A')} PSI")
    c8.metric("⏱️ Run Time",     fmt_hours(rec.get('running_hours', 0)))

    c9, c10, c11, c12 = st.columns(4)
    c9.metric("📳 Vibration",    f"{rec.get('engine_vibration','N/A')}")
    c10.metric("💨 Turbo",       f"{rec.get('turbo_boost',0)} PSI")
    c11.metric("⚡ Alternator",  f"{rec.get('alternator_voltage','N/A')} V")
    c12.metric("📍 Odometer",    f"{rec.get('odometer',0):.0f} km")

    ca, cb, cc, cd = st.columns(4)
    ca.metric("🦶 Brake",        f"{rec.get('brake_pressure',0)} %")
    cb.metric("🦶 Accel",        f"{rec.get('accelerator_pct',0)} %")
    cc.metric("⚙️ Clutch/min",   f"{rec.get('clutch_shifts_per_min',0)}")
    cd.metric("🔄 Steering",     f"{rec.get('steering_angle',0)} deg")

    t1, t2, t3, t4 = st.columns(4)
    t1.metric("🔵 Tyre FL",  f"{rec.get('tyre_pressure_fl','N/A')} PSI")
    t2.metric("🔵 Tyre FR",  f"{rec.get('tyre_pressure_fr','N/A')} PSI")
    t3.metric("🔵 Tyre RL",  f"{rec.get('tyre_pressure_rl','N/A')} PSI")
    t4.metric("🔵 Tyre RR",  f"{rec.get('tyre_pressure_rr','N/A')} PSI")

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("🏥 Health",      f"{rec.get('health_score',100)}")
    sc2.metric("🏆 Safety",      f"{rec.get('driver_safety_score',100)}")
    sc3.metric("🔧 Maintenance", "Required" if rec.get('maintenance_required') else "OK")
    sc4.metric("🌬️ Headwind",    f"{rec.get('headwind_speed',0)} km/h")

    e1, e2, e3, _ = st.columns(4)
    e1.metric("🌡️ Ambient",      f"{rec.get('ambient_temp',30)} C")
    e2.metric("📦 Load",         f"{rec.get('load_weight_pct',0)} %")
    e3.metric("📶 GPS Signal",   f"{rec.get('gps_signal',100)} %")

    if rec.get("driving_mode"):
        st.markdown(
            f"**Mode:** `{rec['driving_mode'].upper()}` | "
            f"**Heading:** `{rec.get('heading',0):.0f} deg` | "
            f"**GPS:** `{rec.get('latitude',0):.4f}, {rec.get('longitude',0):.4f}`"
        )
    if rec.get("timestamp"):
        st.caption(f"🕐 {rec['timestamp']}  |  📡 Source: {rec.get('_source','mongodb')}")
    if rec.get("harsh_braking") or rec.get("harsh_acceleration"):
        st.error(
            f"⚠️ Harsh Event — "
            f"{'Braking ' if rec.get('harsh_braking') else ''}"
            f"{'Acceleration' if rec.get('harsh_acceleration') else ''}"
        )


# ════════════════════════════════════════════════════════════
# PDF REPORT GENERATOR
# ════════════════════════════════════════════════════════════

def generate_driver_pdf(vehicle_id: str, rec: dict) -> bytes:
    buf    = io.BytesIO()
    doc    = SimpleDocTemplate(buf, pagesize=A4,
                               leftMargin=2*cm, rightMargin=2*cm,
                               topMargin=2*cm,  bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("T2", parent=styles["Title"],   fontSize=20,
                              textColor=colors.HexColor("#00aacc"), spaceAfter=6)
    h1_s    = ParagraphStyle("H1", parent=styles["Heading1"],fontSize=13,
                              textColor=colors.HexColor("#003366"), spaceBefore=12, spaceAfter=4)
    norm_s  = ParagraphStyle("N",  parent=styles["Normal"],  fontSize=10, spaceAfter=4)
    sm_s    = ParagraphStyle("S",  parent=styles["Normal"],  fontSize=8,
                              textColor=colors.grey, spaceAfter=2)

    def make_table(data, widths):
        t = Table(data, colWidths=widths)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0,0),(-1,0), colors.HexColor("#003366")),
            ("TEXTCOLOR",  (0,0),(-1,0), colors.white),
            ("FONTNAME",   (0,0),(-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0),(-1,0), 10),
            ("ALIGN",      (0,0),(-1,-1),"CENTER"),
            ("VALIGN",     (0,0),(-1,-1),"MIDDLE"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#f0f4ff"),colors.white]),
            ("GRID",       (0,0),(-1,-1), 0.5, colors.lightgrey),
            ("ROWHEIGHT",  (0,0),(-1,-1), 0.8*cm),
            ("FONTSIZE",   (0,1),(-1,-1), 9),
        ]))
        return t

    story = []
    story.append(Paragraph("Fleet Telemetry System v2", sm_s))
    story.append(Paragraph("Driver and Vehicle Safety Report", title_s))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#00aacc")))
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        f"<b>Vehicle:</b> {vehicle_id}    "
        f"<b>Type:</b> {rec.get('vehicle_type','N/A')}    "
        f"<b>Generated:</b> {datetime.now().strftime('%d %b %Y  %H:%M:%S')}",
        norm_s
    ))
    story.append(Spacer(1, 0.4*cm))

    ss = rec.get("driver_safety_score", 100)
    hs = rec.get("health_score", 100)
    sv = "SAFE DRIVER" if ss >= 80 else ("MODERATE RISK" if ss >= 60 else "HIGH RISK")
    hv = "GOOD CONDITION" if hs >= 70 else ("FAIR — MONITOR" if hs >= 40 else "POOR — SERVICE NOW")

    story.append(Paragraph("Safety Assessment", h1_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    story.append(make_table([
        ["Metric", "Score", "Status"],
        ["Driver Safety Score",  f"{ss} / 100", sv],
        ["Vehicle Health Score", f"{hs} / 100", hv],
        ["Maintenance Required", "YES" if rec.get("maintenance_required") else "NO",
         "Schedule Service" if rec.get("maintenance_required") else "OK"],
    ], [6*cm, 4*cm, 7*cm]))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("Driving Behavior", h1_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    story.append(make_table([
        ["Parameter", "Value", "Assessment"],
        ["Harsh Braking",      "YES" if rec.get("harsh_braking")     else "NO",
         "Detected" if rec.get("harsh_braking")     else "Clear"],
        ["Harsh Acceleration", "YES" if rec.get("harsh_acceleration") else "NO",
         "Detected" if rec.get("harsh_acceleration") else "Clear"],
        ["Brake Pressure",     f"{rec.get('brake_pressure',0):.1f} %",
         "High"    if rec.get("brake_pressure", 0) > 80 else "Normal"],
        ["Accelerator",        f"{rec.get('accelerator_pct',0):.1f} %",
         "Aggressive" if rec.get("accelerator_pct", 0) > 88 else "Normal"],
        ["Steering Angle",     f"{rec.get('steering_angle',0):.1f} deg",
         "Sharp Turn" if abs(rec.get("steering_angle", 0)) > 35 else "Normal"],
        ["Clutch Shifts/min",  f"{rec.get('clutch_shifts_per_min',0):.1f}", "Normal"],
    ], [6*cm, 4*cm, 7*cm]))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("Telemetry Snapshot", h1_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    story.append(make_table([
        ["Parameter", "Value", "Parameter", "Value"],
        ["Speed",        f"{rec.get('speed',0)} km/h",    "Engine Temp",   f"{rec.get('engine_temp',0)} C"],
        ["RPM",          f"{int(rec.get('rpm',0))}",       "Coolant Temp",  f"{rec.get('coolant_temp',0)} C"],
        ["Fuel Level",   f"{rec.get('fuel_level',0)} %",   "Oil Pressure",  f"{rec.get('oil_pressure',0)} PSI"],
        ["Battery",      f"{rec.get('battery_level',0)} %","Vibration",     f"{rec.get('engine_vibration',0)}"],
        ["Odometer",     f"{rec.get('odometer',0):.0f} km","Run Time",      fmt_hours(rec.get('running_hours',0))],
        ["Driving Mode", rec.get('driving_mode','N/A').upper(), "Load",     f"{rec.get('load_weight_pct',0):.1f} %"],
    ], [4.5*cm, 3*cm, 4.5*cm, 5*cm]))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("Tyre Pressures", h1_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    story.append(make_table([
        ["Position", "Pressure (PSI)", "Status"],
        ["Front Left",  f"{rec.get('tyre_pressure_fl',0):.1f}", "Low" if rec.get('tyre_pressure_fl',32)<26 else "OK"],
        ["Front Right", f"{rec.get('tyre_pressure_fr',0):.1f}", "Low" if rec.get('tyre_pressure_fr',32)<26 else "OK"],
        ["Rear Left",   f"{rec.get('tyre_pressure_rl',0):.1f}", "Low" if rec.get('tyre_pressure_rl',32)<26 else "OK"],
        ["Rear Right",  f"{rec.get('tyre_pressure_rr',0):.1f}", "Low" if rec.get('tyre_pressure_rr',32)<26 else "OK"],
    ], [5*cm, 5*cm, 7*cm]))
    story.append(Spacer(1, 0.4*cm))

    story.append(Paragraph("Recommendations", h1_s))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.lightgrey))
    story.append(Spacer(1, 0.2*cm))
    recs_list = []
    if rec.get("maintenance_required"):  recs_list.append("URGENT: Schedule maintenance immediately — health score below threshold.")
    if rec.get("harsh_braking"):         recs_list.append("Driver training recommended — repeated harsh braking detected.")
    if rec.get("harsh_acceleration"):    recs_list.append("Advise driver to reduce aggressive acceleration.")
    if rec.get("oil_pressure",100) < 30: recs_list.append("Oil pressure critically low — inspect oil system before next trip.")
    if rec.get("engine_temp",0) > 100:   recs_list.append("Engine running hot — check coolant levels and radiator.")
    if rec.get("fuel_level",100) < 15:   recs_list.append("Fuel level low — refuel at earliest opportunity.")
    if not recs_list:                    recs_list.append("All systems normal. No immediate action required.")
    for r_item in recs_list:
        story.append(Paragraph(f"- {r_item}", norm_s))

    story.append(Spacer(1, 0.6*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#00aacc")))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        "Auto-generated by Fleet Telemetry System v2. Contact fleet operations manager for queries.", sm_s
    ))
    doc.build(story)
    return buf.getvalue()


# ════════════════════════════════════════════════════════════
# HEADER
# ════════════════════════════════════════════════════════════

counts = get_alert_counts()
hdr, bell = st.columns([9, 1])
with hdr:
    st.markdown("<div class='dash-title'>🚗 Fleet Telemetry Dashboard v2</div>", unsafe_allow_html=True)
    st.markdown("<div class='dash-sub'>Chennai Fleet  •  100 Vehicles  •  Redis + MongoDB  •  Real-time Alerting</div>", unsafe_allow_html=True)
with bell:
    st.markdown("<br>", unsafe_allow_html=True)
    if counts["total"] > 0:
        st.markdown(f"<div style='text-align:center;font-size:26px'>🔔<span class='bell-badge'>{counts['total']}</span></div>", unsafe_allow_html=True)
        if counts["critical"] > 0:
            st.markdown(f"<div style='text-align:center;color:#ff4444;font-size:11px'>{counts['critical']} critical</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div style='text-align:center;font-size:26px'>🔕</div>", unsafe_allow_html=True)
        st.markdown("<div style='text-align:center;color:#00ff88;font-size:11px'>All clear</div>", unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 Vehicle Lookup",
    "🚘 Fleet Summary",
    "📈 Live Charts",
    "🗺️ Fleet Map",
    "🚨 Alerts",
    "📊 Fleet Analytics"
])


# ════════════════════════════════════════════════════════════
# TAB 1 — Vehicle Lookup
# ════════════════════════════════════════════════════════════
with tab1:
    st.markdown("#### 🔍 Search Vehicle")
    c1, c2 = st.columns(2)
    with c1:
        vid_input = st.text_input("Vehicle ID", placeholder="e.g. TRUCK-001, CAR-005, BUS-003")
    with c2:
        st.selectbox("Type", ["All","SCOOTY","BIKE","CAR","PICKUP","VAN","TRUCK","BUS"])
    st.divider()

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("📅 Fetch Past Vehicle Data", key="toggle_past"):
            st.session_state.show_past = not st.session_state.show_past
    with bc2:
        fetch_now = st.button("⚡ Present Time", key="present")

    # Past data panel
    if st.session_state.show_past:
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("##### 🕐 Select Date & Time")
        dc1, dc2 = st.columns(2)
        with dc1: sel_date = st.date_input("Date")
        with dc2: sel_time = st.time_input("Time")
        sel_dt = datetime.combine(sel_date, sel_time).replace(tzinfo=timezone.utc)
        diff   = datetime.now(timezone.utc) - sel_dt
        if   diff <= timedelta(hours=1):  lyr, layer = "🔥 HOT — per-second",  "hot"
        elif diff <= timedelta(days=1):   lyr, layer = "🌡 WARM — per-minute", "warm"
        elif diff <= timedelta(days=3):   lyr, layer = "❄ COLD — hourly",      "cold"
        elif diff <= timedelta(days=365): lyr, layer = "🧊 ARCHIVE — daily",   "archive"
        else:                             lyr, layer = "📦 PERMANENT — yearly","permanent"
        st.info(f"**Storage Layer:** {lyr}")
        if st.button("🔍 Search Past", key="search_past"):
            if not vid_input.strip():
                st.warning("Enter a Vehicle ID")
            else:
                vid = vid_input.strip().upper()
                with st.spinner(f"Fetching past data for {vid}..."):
                    try:
                        if layer == "hot":
                            r = requests.get(f"{API_BASE}/api/telemetry/{vid}/latest", timeout=30)
                        else:
                            r = requests.get(f"{API_BASE}/api/telemetry/{vid}/smart",
                                             params={"selected_datetime": sel_dt.isoformat()}, timeout=30)
                        if r.status_code == 200:
                            res = r.json()
                            rec = res["data"][0] if "data" in res and res["data"] else res
                            st.success(f"✅ {res.get('total_records',1)} records — {res.get('storage_layer', lyr)}")
                            display_metrics(rec)
                            if "data" in res and len(res["data"]) > 1:
                                st.dataframe(pd.DataFrame(res["data"]).drop(columns=["_id"], errors="ignore"), use_container_width=True)
                        elif r.status_code == 404:
                            st.error(f"No data for **{vid}**")
                        else:
                            st.error(f"API error {r.status_code}")
                    except Exception as e:
                        st.error(f"Error: {e}")

    # Present Time
    if fetch_now:
        if not vid_input.strip():
            st.warning("Enter a Vehicle ID")
        else:
            vid = vid_input.strip().upper()
            with st.spinner(f"Fetching live data for {vid}..."):
                try:
                    r = requests.get(f"{API_BASE}/api/telemetry/{vid}/latest", timeout=30)
                    if r.status_code == 200:
                        rec = r.json()
                        st.success(f"⚡ Live reading for **{vid}**")
                        display_metrics(rec)
                        # PDF Export
                        st.divider()
                        st.markdown("##### 📄 Driver Safety Report")
                        col_pdf, col_info = st.columns([1, 3])
                        with col_pdf:
                            pdf_bytes = generate_driver_pdf(vid, rec)
                            st.download_button(
                                label="📥 Download PDF",
                                data=pdf_bytes,
                                file_name=f"{vid}_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
                                mime="application/pdf",
                                key="pdf_dl"
                            )
                        with col_info:
                            st.info("PDF includes: Safety Score, Harsh Events, Health Assessment, Tyre Pressures, Telemetry Snapshot & Recommendations.")
                    elif r.status_code == 404:
                        st.error(f"No data for **{vid}**")
                    else:
                        st.error(f"API error {r.status_code}")
                except Exception as e:
                    st.error(f"Error: {e}")


# ════════════════════════════════════════════════════════════
# TAB 2 — Fleet Summary
# ════════════════════════════════════════════════════════════
with tab2:
    st.markdown("#### 🚘 Fleet Summary")

    FUEL_L100 = {"SCOOTY":2.0,"BIKE":3.5,"CAR":7.0,"PICKUP":12.0,"VAN":14.0,"TRUCK":25.0,"BUS":30.0}
    DAILY_KM  = {"SCOOTY":40, "BIKE":60, "CAR":80, "PICKUP":120,"VAN":130,"TRUCK":200,"BUS":180}

    if st.button("🔄 Refresh Fleet", key="fleet"):
        with st.spinner("Loading fleet..."):
            try:
                r = requests.get(f"{API_BASE}/api/vehicles/summary", timeout=60)
                if r.status_code == 200:
                    st.session_state.fleet_data = r.json()
                    st.session_state.fleet_df   = pd.DataFrame(st.session_state.fleet_data["vehicles"])
                    st.session_state.fuel_results = None  # reset fuel on refresh
                else:
                    st.error(f"API error: {r.status_code}")
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state.fleet_data is not None:
        result   = st.session_state.fleet_data
        vehicles = result["vehicles"]
        df       = st.session_state.fleet_df

        st.success(f"✅ {result['total_vehicles']} vehicles active")

        # Fleet KPIs
        ka,kb,kc,kd,ke,kf = st.columns(6)
        ka.metric("Vehicles",       result['total_vehicles'])
        kb.metric("Avg Speed",      f"{df['speed'].mean():.1f} km/h")
        kc.metric("Avg Eng Temp",   f"{df['engine_temp'].mean():.1f} C")
        kd.metric("Avg Fuel",       f"{df['fuel_level'].mean():.1f} %")
        ke.metric("Avg Health",     f"{df['health_score'].mean():.1f}")
        kf.metric("🔧 Need Maint",  int(df['maintenance_required'].sum()))
        st.divider()

        # Predictive Maintenance Risk Cards
        st.markdown("#### 🔧 Predictive Maintenance — Risk Assessment")
        st.caption("Vehicles approaching or past maintenance threshold, ranked by urgency.")
        at_risk = sorted(
            [v for v in vehicles if v.get("health_score", 100) < 75],
            key=lambda x: x.get("health_score", 100)
        )
        if not at_risk:
            st.success("✅ All vehicles healthy (score >= 75). No maintenance needed.")
        else:
            rk1, rk2, rk3 = st.columns(3)
            rk1.metric("🔴 Critical (<40)",  len([v for v in at_risk if v.get("health_score",100) < 40]))
            rk2.metric("🟠 High (40-60)",    len([v for v in at_risk if 40 <= v.get("health_score",100) < 60]))
            rk3.metric("🟡 Medium (60-75)",  len([v for v in at_risk if 60 <= v.get("health_score",100) < 75]))
            st.markdown("<br>", unsafe_allow_html=True)
            for i in range(0, min(len(at_risk), 12), 3):
                cols = st.columns(3)
                for j, v in enumerate(at_risk[i:i+3]):
                    hs  = v.get("health_score", 100)
                    hrs = fmt_hours(v.get("running_hours", 0))
                    if hs < 40:    css, lbl, em = "maint-crit","CRITICAL","🔴"
                    elif hs < 60:  css, lbl, em = "maint-high","HIGH RISK","🟠"
                    else:          css, lbl, em = "maint-med","MONITOR","🟡"
                    maint = "<br><b style='color:#ff4444'>MAINTENANCE REQUIRED</b>" if v.get("maintenance_required") else ""
                    cols[j].markdown(
                        f"<div class='{css}'><b>{em} {v['vehicle_id']}</b> "
                        f"<span style='font-size:10px;opacity:.7'>({v.get('vehicle_type','')})</span><br>"
                        f"Health: <b>{hs}</b> | {lbl}<br>"
                        f"Run: {hrs} | {v.get('speed',0):.0f} km/h{maint}</div>",
                        unsafe_allow_html=True
                    )
        st.divider()

        # Health Matrix
        st.markdown("#### 🏥 Vehicle Health Matrix")
        st.caption("🟢 Good (>=70)   🟡 Fair (40-69)   🔴 Poor (<40)")
        mc = st.columns(6)
        for i, v in enumerate(vehicles):
            hs = v.get("health_score", 100)
            if hs >= 70:   bg, em = "#0d2e1a","🟢"
            elif hs >= 40: bg, em = "#2e1f0d","🟡"
            else:          bg, em = "#2e0d0d","🔴"
            mnt = "🔧" if v.get("maintenance_required") else ""
            mc[i % 6].markdown(
                f"<div style='background:{bg};border-radius:8px;padding:8px;"
                f"margin:3px;text-align:center;font-size:11px;'>"
                f"{em}<b>{v['vehicle_id']}</b><br>Health:{hs}<br>{v.get('speed',0):.0f}km/h {mnt}</div>",
                unsafe_allow_html=True
            )
        st.divider()

        # Full Fleet Table
        st.markdown("#### 📋 Full Fleet Table")
        sd = df[["vehicle_id","vehicle_type","speed","engine_temp","rpm",
                  "fuel_level","battery_level","health_score","driver_safety_score",
                  "maintenance_required","driving_mode","running_hours"]].copy()
        sd["running_hours"] = sd["running_hours"].apply(fmt_hours)
        sd.columns = ["ID","Type","Speed","Eng Temp","RPM","Fuel%","Batt%",
                      "Health","Safety","Maint","Mode","Run Time"]
        st.dataframe(sd, use_container_width=True)
        st.divider()

        # Fuel Cost Calculator
        st.markdown("#### ⛽ Fuel Cost Calculator")
        st.caption("Estimate daily/monthly fleet fuel costs based on vehicle type and real-world consumption rates.")
        fc1, fc2, fc3 = st.columns(3)
        with fc1: fuel_price     = st.number_input("Fuel Price (Rs/litre)", min_value=50.0, max_value=200.0, value=103.0, step=0.5, key="fp")
        with fc2: operating_days = st.number_input("Operating Days/Month",  min_value=1, max_value=31, value=26, step=1, key="od")
        with fc3: utilization    = st.slider("Fleet Utilization %", 50, 100, 80, 5, key="ut")

        if st.button("💰 Calculate Costs", key="calc"):
            type_counts = df["vehicle_type"].value_counts().to_dict()
            rows = []; total_daily = 0
            for vtype, count in sorted(type_counts.items()):
                l100 = FUEL_L100.get(vtype, 10)
                dkm  = DAILY_KM.get(vtype, 100) * (utilization / 100)
                dL   = dkm / 100 * l100
                dcp  = dL * fuel_price
                dca  = dcp * count
                mc_  = dca * operating_days
                total_daily += dca
                rows.append({
                    "Type": vtype, "Count": count,
                    "L/100km": f"{l100}", "Avg Daily km": f"{dkm:.0f}",
                    "Daily L/veh": f"{dL:.1f}", "Daily Cost/veh": f"Rs {dcp:,.0f}",
                    "Fleet Daily": f"Rs {dca:,.0f}", "Monthly Total": f"Rs {mc_:,.0f}",
                })
            total_m = total_daily * operating_days
            total_y = total_m * 12
            st.session_state.fuel_results = {
                "rows": rows, "total_daily": total_daily,
                "total_m": total_m, "total_y": total_y,
                "utilization": utilization, "fuel_price": fuel_price,
                "operating_days": operating_days
            }

        # Always render fuel results if they exist
        if st.session_state.fuel_results:
            fr = st.session_state.fuel_results
            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("📅 Daily",   f"Rs {fr['total_daily']:,.0f}")
            sc2.metric("📆 Monthly", f"Rs {fr['total_m']:,.0f}")
            sc3.metric("📅 Annual",  f"Rs {fr['total_y']:,.0f}")
            st.dataframe(pd.DataFrame(fr["rows"]), use_container_width=True)
            st.caption(f"Based on {fr['utilization']}% utilization, Rs {fr['fuel_price']}/L, {fr['operating_days']} operating days/month.")
    else:
        st.info("Click **🔄 Refresh Fleet** to load fleet data.")


# ════════════════════════════════════════════════════════════
# TAB 3 — Live Charts
# ════════════════════════════════════════════════════════════
with tab3:
    st.markdown("#### 📈 Telemetry Charts")
    cc1, cc2 = st.columns(2)
    with cc1: chart_vid  = st.text_input("Vehicle ID", placeholder="e.g. TRUCK-001", key="cv")
    with cc2: chart_mins = st.slider("Minutes back", 1, 60, 10)
    chart_group = st.selectbox("Chart Group", [
        "Core (Speed, RPM, Temp)",
        "Driver Behavior",
        "Engine Health",
        "Tyre Pressures",
        "Resources (Fuel, Battery)",
        "Scores (Health, Safety)"
    ])
    if st.button("📈 Load Charts", key="charts"):
        if not chart_vid.strip():
            st.warning("Enter a Vehicle ID")
        else:
            vid = chart_vid.strip().upper()
            with st.spinner("Loading..."):
                try:
                    r = requests.get(f"{API_BASE}/api/telemetry/{vid}",
                                     params={"minutes": chart_mins}, timeout=10)
                    if r.status_code == 200:
                        df = pd.DataFrame(r.json()["data"])
                        df["timestamp"] = pd.to_datetime(df["timestamp"])
                        df = df.sort_values("timestamp")
                        st.success(f"✅ {r.json()['total_records']} records for {vid}")
                        if chart_group == "Core (Speed, RPM, Temp)":
                            st.markdown("**🚀 Speed (km/h)**");           st.line_chart(df.set_index("timestamp")[["speed"]])
                            st.markdown("**⚙️ RPM**");                    st.line_chart(df.set_index("timestamp")[["rpm"]])
                            st.markdown("**🌡️ Engine & Coolant Temp**");  st.line_chart(df.set_index("timestamp")[["engine_temp","coolant_temp"]])
                        elif chart_group == "Driver Behavior":
                            st.markdown("**🦶 Brake & Accelerator**");    st.line_chart(df.set_index("timestamp")[["brake_pressure","accelerator_pct"]])
                            st.markdown("**⚙️ Clutch Shifts/min**");      st.line_chart(df.set_index("timestamp")[["clutch_shifts_per_min"]])
                            st.markdown("**🔄 Steering Angle**");         st.line_chart(df.set_index("timestamp")[["steering_angle"]])
                        elif chart_group == "Engine Health":
                            st.markdown("**🛢️ Oil Pressure (PSI)**");     st.line_chart(df.set_index("timestamp")[["oil_pressure"]])
                            st.markdown("**📳 Engine Vibration**");       st.line_chart(df.set_index("timestamp")[["engine_vibration"]])
                            if "turbo_boost" in df.columns:
                                st.markdown("**💨 Turbo Boost**");        st.line_chart(df.set_index("timestamp")[["turbo_boost"]])
                            st.markdown("**⚡ Alternator Voltage**");     st.line_chart(df.set_index("timestamp")[["alternator_voltage"]])
                        elif chart_group == "Tyre Pressures":
                            st.markdown("**🔵 All 4 Tyres (PSI)**");
                            st.line_chart(df.set_index("timestamp")[["tyre_pressure_fl","tyre_pressure_fr","tyre_pressure_rl","tyre_pressure_rr"]])
                        elif chart_group == "Resources (Fuel, Battery)":
                            st.markdown("**⛽ Fuel & 🔋 Battery**");      st.line_chart(df.set_index("timestamp")[["fuel_level","battery_level"]])
                            st.markdown("**⏱️ Run Time (hours)**");       st.line_chart(df.set_index("timestamp")[["running_hours"]])
                        elif chart_group == "Scores (Health, Safety)":
                            st.markdown("**🏥 Health & 🏆 Safety**");     st.line_chart(df.set_index("timestamp")[["health_score","driver_safety_score"]])
                    elif r.status_code == 404: st.error(f"No data for **{vid}**")
                    else:                      st.error(f"API error {r.status_code}")
                except Exception as e:
                    st.error(f"Error: {e}")


# ════════════════════════════════════════════════════════════
# TAB 4 — Fleet Map
# ════════════════════════════════════════════════════════════
with tab4:
    st.markdown("#### 🗺️ Live Fleet Map — Chennai")
    st.caption("🟢 Healthy   🟡 Fair   🔴 Needs Maintenance")

    mc1, mc2 = st.columns(2)
    with mc1:
        if st.button("🗺️ Load Map", key="map"):
            with st.spinner("Loading vehicle locations..."):
                try:
                    r = requests.get(f"{API_BASE}/api/vehicles/locations", timeout=60)
                    if r.status_code == 200:
                        st.session_state.map_vehicles = r.json()["vehicles"]
                    else:
                        st.error(f"API error: {r.status_code}")
                except Exception as e:
                    st.error(f"Error: {e}")

    # ── Geospatial Search ──────────────────────────────────
    with mc2:
        st.markdown("**📍 Geospatial Search**")
        st.caption("Find all vehicles within a radius of any GPS point (uses MongoDB 2dsphere index)")
    gc1, gc2, gc3, gc4 = st.columns(4)
    with gc1: geo_lat    = st.number_input("Latitude",  value=13.0827, format="%.4f", key="glat")
    with gc2: geo_lon    = st.number_input("Longitude", value=80.2707, format="%.4f", key="glon")
    with gc3: geo_radius = st.number_input("Radius (km)", value=5.0, min_value=0.5, max_value=50.0, step=0.5, key="grad")
    with gc4:
        st.markdown("<br>", unsafe_allow_html=True)
        run_geo = st.button("🔍 Search Nearby", key="geo")

    if run_geo:
        with st.spinner(f"Querying vehicles within {geo_radius}km..."):
            try:
                r = requests.get(f"{API_BASE}/api/vehicles/nearby",
                                 params={"lat": geo_lat, "lon": geo_lon, "radius_km": geo_radius},
                                 timeout=15)
                if r.status_code == 200:
                    res = r.json()
                    st.success(f"✅ {res['count']} vehicles within {geo_radius}km of ({geo_lat:.4f}, {geo_lon:.4f})")
                    if res["vehicles"]:
                        gdf = {"ID":[], "Type":[], "Speed":[], "Health":[], "Mode":[], "Temp":[]}
                        for v in res["vehicles"]:
                            gdf["ID"].append(v["vehicle_id"])
                            gdf["Type"].append(v["vehicle_type"])
                            gdf["Speed"].append(f"{v.get('speed',0):.1f} km/h")
                            gdf["Health"].append(v.get("health_score",100))
                            gdf["Mode"].append(v.get("driving_mode","").upper())
                            gdf["Temp"].append(f"{v.get('engine_temp',0):.1f} C")
                        import pandas as pd
                        st.dataframe(pd.DataFrame(gdf), use_container_width=True, hide_index=True)
                    # Plot just the nearby vehicles on a smaller map
                    if res["vehicles"]:
                        gmap = folium.Map(location=[geo_lat, geo_lon], zoom_start=13, tiles="CartoDB dark_matter")
                        folium.Circle(location=[geo_lat, geo_lon], radius=geo_radius*1000,
                                      color="#00d4ff", fill=False, weight=2,
                                      tooltip=f"{geo_radius}km radius").add_to(gmap)
                        folium.Marker(location=[geo_lat, geo_lon],
                                      tooltip="Search center",
                                      icon=folium.Icon(color="blue", icon="crosshairs", prefix="fa")).add_to(gmap)
                        for v in res["vehicles"]:
                            hs = v.get("health_score",100)
                            color = "green" if hs>=70 else ("orange" if hs>=40 else "red")
                            folium.CircleMarker(
                                location=[v["latitude"], v["longitude"]], radius=7, color=color,
                                fill=True, fill_color=color, fill_opacity=0.9,
                                tooltip=f"{v['vehicle_id']} | {v.get('speed',0):.0f}km/h | Health:{hs}"
                            ).add_to(gmap)
                        st_folium(gmap, width=None, height=400, key="geo_map")
                else:
                    st.error(f"API error: {r.status_code}")
            except Exception as e:
                st.error(f"Geospatial query error: {e}")

    st.divider()

    if st.session_state.map_vehicles is not None:
        vehicles = st.session_state.map_vehicles
        m = folium.Map(location=[13.0827, 80.2707], zoom_start=11, tiles="CartoDB dark_matter")
        for v in vehicles:
            lat = v.get("latitude", 0); lon = v.get("longitude", 0)
            if lat == 0 and lon == 0: continue
            hs    = v.get("health_score", 100)
            color = "green" if hs >= 70 else ("orange" if hs >= 40 else "red")
            popup_html = (
                f"<div style='font-family:monospace;min-width:180px'>"
                f"<b>{v['vehicle_id']}</b> ({v.get('vehicle_type','')})<br>"
                f"Speed: {v.get('speed',0):.1f} km/h | Health: {hs}<br>"
                f"Mode: {v.get('driving_mode','').upper()}<br>"
                f"{'MAINTENANCE REQUIRED' if v.get('maintenance_required') else 'OK'}"
                f"</div>"
            )
            folium.CircleMarker(
                location=[lat, lon], radius=6, color=color,
                fill=True, fill_color=color, fill_opacity=0.8,
                popup=folium.Popup(popup_html, max_width=200),
                tooltip=f"{v['vehicle_id']} | {v.get('speed',0):.0f} km/h"
            ).add_to(m)
        st_folium(m, width=None, height=520, key="folium_map")
        st.success(f"✅ {len(vehicles)} vehicles plotted | Click Load Map to refresh")


# ════════════════════════════════════════════════════════════
# TAB 5 — Alerts
# ════════════════════════════════════════════════════════════
with tab5:
    st.markdown("#### 🚨 Fleet Alerts")
    fa1, fa2, fa3 = st.columns(3)
    with fa1: fvid   = st.text_input("Filter Vehicle ID", placeholder="optional")
    with fa2: fsev   = st.selectbox("Severity", ["All","critical","warning"])
    with fa3: funres = st.checkbox("Unresolved only", value=True)
    if st.button("🔄 Refresh Alerts", key="ra"):
        with st.spinner("Loading alerts..."):
            try:
                params = {"limit": 100, "unresolved_only": funres}
                if fvid.strip():  params["vehicle_id"] = fvid.strip().upper()
                if fsev != "All": params["severity"]   = fsev
                r = requests.get(f"{API_BASE}/api/alerts", params=params, timeout=10)
                if r.status_code == 200:
                    alerts = r.json()["alerts"]
                    crits  = [a for a in alerts if a["severity"] == "critical"]
                    warns  = [a for a in alerts if a["severity"] == "warning"]
                    ac1, ac2, ac3 = st.columns(3)
                    ac1.metric("🔴 Critical", len(crits))
                    ac2.metric("🟡 Warning",  len(warns))
                    ac3.metric("📋 Total",    len(alerts))
                    st.divider()
                    if not alerts:
                        st.success("✅ No alerts — fleet operating normally!")
                    else:
                        for a in alerts:
                            css  = "alert-critical" if a["severity"] == "critical" else "alert-warning"
                            icon = "🚨" if a["severity"] == "critical" else "⚠️"
                            res  = "Resolved" if a.get("resolved") else "Active"
                            st.markdown(
                                f"<div class='{css}'>"
                                f"<strong>{icon} {a.get('alert_type','').replace('_',' ')}</strong>"
                                f"  <span style='font-size:11px;opacity:.7'>{res}</span><br>"
                                f"<b>Vehicle:</b> {a.get('vehicle_id','')} ({a.get('vehicle_type','')})<br>"
                                f"{a.get('message','')}<br>"
                                f"<span style='font-size:11px;opacity:.6'>🕐 {a.get('timestamp','')}</span>"
                                f"</div>",
                                unsafe_allow_html=True
                            )
                else:
                    st.error(f"API error: {r.status_code}")
            except Exception as e:
                st.error(f"Error: {e}")
    else:
        st.info("Click **🔄 Refresh Alerts** to load alerts.")


# ════════════════════════════════════════════════════════════
# TAB 6 — Fleet Analytics (NEW)
# ════════════════════════════════════════════════════════════
with tab6:
    st.markdown("#### 📊 Fleet Analytics — Historical Trends & Type Comparison")
    trend_mins = st.slider("Trend window (minutes back)", 5, 120, 30, key="tm")

    if st.button("📊 Load Analytics", key="la"):
        with st.spinner("Fetching analytics data..."):

            # Fleet-wide trend lines
            try:
                rt = requests.get(f"{API_BASE}/api/analytics/trends",
                                  params={"minutes": trend_mins}, timeout=60)
                if rt.status_code == 200 and rt.json()["trends"]:
                    tdf = pd.DataFrame(rt.json()["trends"])
                    tdf["timestamp"] = pd.to_datetime(tdf["timestamp"])
                    tdf = tdf.sort_values("timestamp")
                    st.markdown("---")
                    st.markdown(f"### 📈 Fleet-Wide Trends — Last {trend_mins} Minutes")
                    cola, colb = st.columns(2)
                    with cola:
                        st.markdown("**🏥 Avg Health vs 🏆 Avg Safety Score**")
                        st.line_chart(tdf.set_index("timestamp")[["avg_health","avg_safety"]])
                    with colb:
                        st.markdown("**🚀 Avg Speed vs 🌡️ Avg Engine Temp**")
                        st.line_chart(tdf.set_index("timestamp")[["avg_speed","avg_temp"]])
                    st.markdown("**⛽ Fleet Average Fuel Level (%)**")
                    st.line_chart(tdf.set_index("timestamp")[["avg_fuel"]])
                else:
                    st.info("Not enough trend data yet — keep the simulator running a few more minutes.")
            except Exception as e:
                st.warning(f"Trend data unavailable: {e}")

            # Vehicle type comparison
            try:
                ro = requests.get(f"{API_BASE}/api/analytics/fleet-overview", timeout=10)
                if ro.status_code == 200 and ro.json()["by_type"]:
                    odf = pd.DataFrame(ro.json()["by_type"]).set_index("vehicle_type")
                    st.markdown("---")
                    st.markdown("### 🚗 Vehicle Type Comparison")
                    colc, cold = st.columns(2)
                    with colc:
                        st.markdown("**🏥 Avg Health Score by Type**"); st.bar_chart(odf[["avg_health"]])
                    with cold:
                        st.markdown("**🚀 Avg Speed (km/h) by Type**"); st.bar_chart(odf[["avg_speed"]])
                    cole, colf = st.columns(2)
                    with cole:
                        st.markdown("**⛽ Avg Fuel Level (%) by Type**"); st.bar_chart(odf[["avg_fuel"]])
                    with colf:
                        st.markdown("**🌡️ Avg Engine Temp by Type**"); st.bar_chart(odf[["avg_temp"]])
                    st.markdown("**📋 Full Type Comparison Table**")
                    dsp = odf[["count","avg_speed","avg_health","avg_safety","avg_fuel","avg_temp","maintenance_count"]].copy()
                    dsp.columns = ["Count","Avg Speed","Avg Health","Avg Safety","Avg Fuel%","Avg Temp","Need Maint"]
                    st.dataframe(dsp, use_container_width=True)
            except Exception as e:
                st.warning(f"Type comparison unavailable: {e}")

            # Maintenance risk ranking
            try:
                rr = requests.get(f"{API_BASE}/api/analytics/maintenance-risk", timeout=10)
                if rr.status_code == 200 and rr.json()["vehicles"]:
                    rdf = pd.DataFrame(rr.json()["vehicles"])
                    st.markdown("---")
                    st.markdown("### 🔧 Full Maintenance Risk Ranking")
                    st.caption("All vehicles sorted by health score — worst condition first.")

                    def risk_style(val):
                        if val == "CRITICAL": return "background-color:#4a0000;color:#ff6666"
                        if val == "HIGH":     return "background-color:#3a1a00;color:#ffaa44"
                        if val == "MEDIUM":   return "background-color:#3a3000;color:#ffdd44"
                        return "background-color:#0a1a0a;color:#44ff88"

                    srd = rdf[["vehicle_id","vehicle_type","health_score","risk_level",
                               "oil_pressure","engine_vibration","running_hours",
                               "odometer","maintenance_required","driver_safety_score"]].copy()
                    srd.columns = ["ID","Type","Health","Risk","Oil PSI","Vibration",
                                   "Run Hrs","Odometer","Maint","Safety"]
                    srd["Run Hrs"] = srd["Run Hrs"].apply(lambda x: f"{float(x):.2f}" if x else "0")
                    st.dataframe(
                        srd.style.map(risk_style, subset=["Risk"]),
                        use_container_width=True
                    )

                    st.markdown("---")
                    ct, cb = st.columns(2)
                    with ct:
                        st.markdown("#### 🏆 Top 5 Healthiest Vehicles")
                        t5 = rdf.nlargest(5, "health_score")[["vehicle_id","vehicle_type","health_score","driver_safety_score"]]
                        t5.columns = ["ID","Type","Health","Safety"]
                        st.dataframe(t5, use_container_width=True, hide_index=True)
                    with cb:
                        st.markdown("#### ⚠️ Bottom 5 — Needs Attention")
                        b5 = rdf.nsmallest(5, "health_score")[["vehicle_id","vehicle_type","health_score","risk_level","maintenance_required"]]
                        b5.columns = ["ID","Type","Health","Risk","Maint"]
                        st.dataframe(b5, use_container_width=True, hide_index=True)
            except Exception as e:
                st.warning(f"Risk ranking unavailable: {e}")
    else:
        st.info("Click **📊 Load Analytics** to load historical trends and fleet comparisons.")


# ════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════
st.sidebar.markdown("### 🚗 Fleet Monitor v2")
st.sidebar.markdown("---")
try:
    r = requests.get(f"{API_BASE}/", timeout=3)
    st.sidebar.markdown(
        "<span class='status-online'>● API Online</span>" if r.status_code == 200
        else "<span class='status-offline'>● API Issue</span>",
        unsafe_allow_html=True
    )
except:
    st.sidebar.markdown("<span class='status-offline'>● API Offline</span>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("**🚨 Alerts**")
if counts["critical"] > 0: st.sidebar.error(f"🔴 {counts['critical']} Critical")
if counts["warning"]  > 0: st.sidebar.warning(f"🟡 {counts['warning']} Warnings")
if counts["total"]   == 0: st.sidebar.success("✅ All clear")

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Fleet**\n"
    "🛵 SCOOTY x10 | 🏍 BIKE x10\n"
    "🚗 CAR x20    | 🛻 PICKUP x10\n"
    "🚐 VAN x15    | 🚛 TRUCK x20\n"
    "🚌 BUS x15"
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Storage Architecture**\n"
    "🔥 Hot     -> raw      (1hr)\n"
    "🌡 Warm    -> per-min  (1d)\n"
    "❄ Cold    -> hourly   (3d)\n"
    "🧊 Archive -> daily    (1yr)\n"
    "📦 Permanent -> yearly"
)
st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Alert Types**\n"
    "🌡️ High Engine Temp\n"
    "⚡ Over Speed\n"
    "⛽ Low Fuel (<10%)\n"
    "🔋 Low Battery (<15%)\n"
    "😴 Extended Idle (>10m)\n"
    "🚨 Accident Detected\n"
    "🛢️ Low Oil Pressure\n"
    "🔧 Low Tyre Pressure\n"
    "🔧 Maintenance Required"
)
st.sidebar.markdown("---")
st.sidebar.markdown("**🤖 ML + Edge Computing**")
try:
    es     = requests.get(f"{API_BASE}/api/analytics/edge-stats", timeout=3).json()
    ml     = es.get("ml_models", {})
    trained = ml.get("trained_types", [])
    pending = ml.get("pending_types", {})
    edge    = es.get("edge_computing", {})
    ws_cnt  = es.get("websocket_connections", 0)
    if trained:
        st.sidebar.success(f"✅ Models trained: {', '.join(trained)}")
    for vtype, status in (pending or {}).items():
        st.sidebar.caption(f"⏳ {vtype}: {status}")
    if not trained and not pending:
        st.sidebar.caption("Waiting for data...")
    saved = edge.get("bandwidth_saved_pct", 0)
    st.sidebar.metric("Edge Bandwidth Saved", f"{saved}%")
    st.sidebar.metric("WebSocket Connections", ws_cnt)
except Exception:
    st.sidebar.caption("Simulator not connected yet")
st.sidebar.markdown("---")
if st.sidebar.button("🚪 Logout"):
    st.session_state.logged_in = False
    st.rerun()