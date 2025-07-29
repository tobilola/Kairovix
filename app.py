import streamlit as st
from datetime import datetime, date as date_cls
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import pandas as pd

# -----------------------------
# Firebase init (uses Streamlit secrets)
# -----------------------------
if not firebase_admin._apps:
    firebase_creds = dict(st.secrets["firebase"])
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Kairovix – Lab Scheduler", layout="centered")
st.title("🔬 Kairovix: Smart Lab Equipment Scheduler")
st.markdown("Book time slots for lab equipment in real-time. Powered by **TOBI HealthOps AI**.")

EQUIPMENT_LIST = [
    "IncuCyte", "Confocal Microscope", "Flow Cytometer",
    "Centrifuge", "Nanodrop", "Qubit 4", "QuantStudio 3",
    "Genesis SC", "Biorad ChemiDoc", "C1000 Touch"
]

# Optional color map for calendar
COLOR_MAP = {
    "IncuCyte": "#1E90FF",
    "Confocal Microscope": "#8A2BE2",
    "Flow Cytometer": "#00B894",
    "Centrifuge": "#E17055",
    "Nanodrop": "#FDCB6E",
    "Qubit 4": "#6C5CE7",
    "QuantStudio 3": "#00CEC9",
    "Genesis SC": "#FF7675",
    "Biorad ChemiDoc": "#55EFC4",
    "C1000 Touch": "#0984E3",
}

INCUCYTE_SLOTS = [
    "Top Left", "Top Right",
    "Middle Left", "Middle Right",
    "Bottom Left", "Bottom Right",
]

# -----------------------------
# Booking form (with IncuCyte slot layout)
# -----------------------------
with st.form("booking_form"):
    name = st.text_input("Your Name")
    equipment = st.selectbox("Select Equipment", EQUIPMENT_LIST)
    booking_date = st.date_input("Select Date", value=date_cls.today())
    booking_time = st.time_input("Select Time Slot (24h format)")

    # Slot selection only for IncuCyte
    slot = None
    if equipment == "IncuCyte":
        st.caption("IncuCyte tray slots:")
        # Simple dropdown; we can replace with a clickable grid later
        slot = st.selectbox("Select Tray Slot", INCUCYTE_SLOTS)

    submitted = st.form_submit_button("✅ Submit Booking")

    if submitted:
        # Basic validation
        if not name:
            st.warning("Please enter your name before submitting.")
        elif equipment == "IncuCyte" and not slot:
            st.warning("Please choose a tray slot for IncuCyte.")
        else:
            # Prevent double booking:
            # same equipment + same date + same time (+ same slot for IncuCyte)
            existing_query = db.collection("bookings") \
                .where("equipment", "==", equipment) \
                .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
                .where("time", "==", booking_time.strftime("%H:%M"))

            if equipment == "IncuCyte":
                existing_query = existing_query.where("slot", "==", slot)

            existing = list(existing_query.stream())
            if existing:
                if equipment == "IncuCyte":
                    st.error(
                        f"❌ {equipment} **{slot}** is already booked for "
                        f"{booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}."
                    )
                else:
                    st.error(
                        f"❌ {equipment} is already booked for "
                        f"{booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}."
                    )
            else:
                doc_id = str(uuid.uuid4())
                booking_data = {
                    "name": name.strip(),
                    "equipment": equipment,
                    "date": booking_date.strftime("%Y-%m-%d"),
                    "time": booking_time.strftime("%H:%M"),
                    "timestamp": datetime.utcnow(),
                    "slot": slot if equipment == "IncuCyte" else None
                }
                db.collection("bookings").document(doc_id).set(booking_data)
                success_msg = (
                    f"✅ Booking confirmed for **{equipment}**"
                    f"{f' – **{slot}**' if slot else ''} at "
                    f"**{booking_time.strftime('%H:%M')}** on **{booking_date.strftime('%Y-%m-%d')}**."
                )
                st.success(success_msg)

# -----------------------------
# Recent bookings (optional)
# -----------------------------
st.markdown("---")
if st.checkbox("📋 Show Recent Bookings"):
    try:
        recent_q = db.collection("bookings") \
            .order_by("timestamp", direction=firestore.Query.DESCENDING) \
            .limit(10)
        recent = recent_q.stream()
        found_any = False
        for bk in recent:
            found_any = True
            d = bk.to_dict()
            inc_slot = f" – **{d.get('slot')}**" if d.get("slot") else ""
            st.markdown(
                f"🔹 **{d.get('equipment','?')}**{inc_slot} booked by **{d.get('name','?')}** "
                f"on **{d.get('date','?')} at {d.get('time','?')}**"
            )
        if not found_any:
            st.info("No recent bookings.")
    except Exception as e:
        st.error(f"Error loading recent bookings: {e}")

# -----------------------------
# Upcoming bookings (with filters)
# -----------------------------
st.markdown("---")
st.subheader("📋 Upcoming Bookings")

filter_equipment = st.selectbox("Filter by Equipment", ["All"] + EQUIPMENT_LIST)

use_date_filter = st.checkbox("Filter by a specific date")
if use_date_filter:
    filter_date = st.date_input("Choose date", value=date_cls.today())
else:
    filter_date = None

try:
    q = db.collection("bookings").order_by("timestamp", direction=firestore.Query.DESCENDING)
    rows = []
    for bk in q.stream():
        d = bk.to_dict()
        # Apply filters
        if filter_equipment != "All" and d.get("equipment") != filter_equipment:
            continue
        if filter_date and d.get("date") != filter_date.strftime("%Y-%m-%d"):
            continue
        rows.append([
            d.get("name",""),
            d.get("equipment",""),
            d.get("slot","") if d.get("equipment") == "IncuCyte" else "",
            d.get("date",""),
            d.get("time","")
        ])

    if rows:
        df = pd.DataFrame(rows, columns=["Name", "Equipment", "Slot", "Date", "Time"])
        st.table(df)
    else:
        st.info("No bookings match your filters.")
except Exception as e:
    st.error(f"Error loading bookings: {e}")

# -----------------------------
# 📅 Equipment-Specific Calendar (Interactive)
# -----------------------------
from streamlit_calendar import calendar

st.markdown("---")
st.subheader("📅 Equipment-Specific Calendar")

# Default calendar to IncuCyte (as requested)
default_index = EQUIPMENT_LIST.index("IncuCyte")
equipment_for_calendar = st.selectbox("Select Equipment to View", EQUIPMENT_LIST, index=default_index)

try:
    # Only load events for the selected equipment
    bookings_ref = db.collection("bookings") \
        .where("equipment", "==", equipment_for_calendar) \
        .order_by("date")

    events = []
    for booking in bookings_ref.stream():
        b = booking.to_dict()
        event_date = b.get("date")
        time_str = b.get("time", "00:00")
        # Title includes slot for IncuCyte
        title = f"{b.get('equipment','?')} ({b.get('name','?')})"
        if b.get("equipment") == "IncuCyte" and b.get("slot"):
            title += f" – {b.get('slot')}"

        start = f"{event_date}T{time_str}:00"
        color = COLOR_MAP.get(b.get("equipment",""), "#1E90FF")

        events.append({
            "title": title,
            "start": start,
            "allDay": False,
            "backgroundColor": color,
            "borderColor": color,
        })

    if events:
        calendar_options = {
            "initialView": "dayGridMonth",
            "height": "600px",
            "editable": False,
            "eventDisplay": "block"
        }
        calendar(events, options=calendar_options)
    else:
        st.info(f"No bookings for **{equipment_for_calendar}**.")
except Exception as e:
    st.error(f"Error loading calendar: {e}")

# -----------------------------
# 📊 Analytics Dashboard (with charts)
# -----------------------------
st.markdown("---")
st.subheader("📊 Analytics Dashboard")

try:
    all_stream = db.collection("bookings").stream()

    total_bookings = 0
    equipment_usage = {}
    hourly_usage = {}

    for bk in all_stream:
        d = bk.to_dict()
        total_bookings += 1

        eq = d.get("equipment", "Unknown")
        equipment_usage[eq] = equipment_usage.get(eq, 0) + 1

        # Expect "HH:MM" string
        t = d.get("time", "00:00")
        hour = t[:2]
        hourly_usage[hour] = hourly_usage.get(hour, 0) + 1

    # Top metric
    st.metric("Total Bookings", total_bookings)

    # Equipment usage bar chart
    if equipment_usage:
        st.markdown("### Most Used Equipment")
        eq_df = pd.DataFrame(
            [{"Equipment": k, "Bookings": v} for k, v in equipment_usage.items()]
        ).sort_values("Bookings", ascending=False)
        st.bar_chart(eq_df.set_index("Equipment"))

    # Peak hours bar chart
    if hourly_usage:
        st.markdown("### Peak Booking Hours")
        hr_df = pd.DataFrame(
            [{"Hour": k, "Bookings": v} for k, v in hourly_usage.items()]
        ).sort_values("Hour")
        st.bar_chart(hr_df.set_index("Hour"))

except Exception as e:
    st.error(f"Error loading analytics: {e}")
