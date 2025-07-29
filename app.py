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
# Booking form (Grid slot selection works with st.radio)
# -----------------------------
INCUCYTE_SLOTS = [
    ["Top Left", "Top Right"],
    ["Middle Left", "Middle Right"],
    ["Bottom Left", "Bottom Right"]
]

with st.form("booking_form"):
    name = st.text_input("Your Name")
    equipment = st.selectbox("Select Equipment", EQUIPMENT_LIST)
    booking_date = st.date_input("Select Date", value=date_cls.today())
    booking_time = st.time_input("Select Time Slot (24h format)")

    slot = None
    if equipment == "IncuCyte":
        st.markdown("**Select Tray Slot (Click to select)**")

        # Flatten the grid into one list but keep visual grouping
        slot_choice = st.radio(
            "Choose a slot", 
            options=[slot for row in INCUCYTE_SLOTS for slot in row],
            index=None,
            horizontal=False
        )
        slot = slot_choice

    submitted = st.form_submit_button("✅ Submit Booking")

    if submitted:
        if not name:
            st.warning("Please enter your name before submitting.")
        elif equipment == "IncuCyte" and not slot:
            st.warning("Please select a tray slot for IncuCyte.")
        else:
            # Prevent double booking (also check slot if IncuCyte)
            query = db.collection("bookings") \
                .where("equipment", "==", equipment) \
                .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
                .where("time", "==", booking_time.strftime("%H:%M"))

            if equipment == "IncuCyte":
                query = query.where("slot", "==", slot)

            existing = list(query.stream())

            if existing:
                st.error(
                    f"❌ {equipment} {f'({slot}) ' if slot else ''}"
                    f"is already booked for {booking_time.strftime('%H:%M')} "
                    f"on {booking_date.strftime('%Y-%m-%d')}."
                )
            else:
                booking_data = {
                    "name": name.strip(),
                    "equipment": equipment,
                    "date": booking_date.strftime("%Y-%m-%d"),
                    "time": booking_time.strftime("%H:%M"),
                    "slot": slot if equipment == "IncuCyte" else None,
                    "timestamp": datetime.utcnow()
                }
                db.collection("bookings").document(str(uuid.uuid4())).set(booking_data)
                st.success(
                    f"✅ Booking confirmed for **{equipment}** "
                    f"{f'({slot}) ' if slot else ''}at "
                    f"{booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}."
                )

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

# Default to IncuCyte for convenience
default_index = EQUIPMENT_LIST.index("IncuCyte")
equipment_for_calendar = st.selectbox("Select Equipment to View", EQUIPMENT_LIST, index=default_index)

try:
    bookings_ref = db.collection("bookings") \
        .where("equipment", "==", equipment_for_calendar) \
        .order_by("date")

    events = []
    for booking in bookings_ref.stream():
        b = booking.to_dict()
        start = f"{b['date']}T{b['time']}:00"

        # Include slot if it's IncuCyte
        title = f"{b['equipment']} ({b['name']})"
        if b['equipment'] == "IncuCyte" and b.get('slot'):
            title += f" - {b['slot']}"

        events.append({
            "title": title,
            "start": start,
            "allDay": False,
            "backgroundColor": "#1E90FF",
            "borderColor": "#1E90FF"
        })

    if events:
        calendar(events, options={
            "initialView": "dayGridMonth",
            "height": "600px",
            "editable": False,
            "eventDisplay": "block"
        })
    else:
        st.info(f"No bookings for {equipment_for_calendar}.")

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
