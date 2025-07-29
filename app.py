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
# Booking form (Grid slot selection with booked/available info)
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
    booked_slots = set()

    if equipment == "IncuCyte":
        st.markdown("**Select Tray Slot (Click to select)**")

        # Find already booked slots for this date/time
        try:
            booked_q = db.collection("bookings") \
                .where("equipment", "==", "IncuCyte") \
                .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
                .where("time", "==", booking_time.strftime("%H:%M")) \
                .stream()

            for b in booked_q:
                s = b.to_dict().get("slot")
                if s:
                    booked_slots.add(s)
        except Exception as e:
            st.warning(f"Could not load booked slots: {e}")

        # Show grid with availability
        for row in INCUCYTE_SLOTS:
            cols = st.columns(2)
            for idx, s in enumerate(row):
                tag = "🔒 Booked" if s in booked_slots else "🟢 Available"
                cols[idx].markdown(f"**{s}** — {tag}")

        # Allow only available slots to be selected
        available_slots = [s for row in INCUCYTE_SLOTS for s in row if s not in booked_slots]
        slot = st.radio(
            "Choose an available slot",
            options=available_slots if available_slots else ["No slots available"],
            index=None
        )

    submitted = st.form_submit_button("✅ Submit Booking")

    if submitted:
        if not name:
            st.warning("Please enter your name before submitting.")
        elif equipment == "IncuCyte" and (not slot or slot == "No slots available"):
            st.warning("Please select an available tray slot for IncuCyte.")
        else:
            # Double booking check (extra safe)
            q = db.collection("bookings") \
                .where("equipment", "==", equipment) \
                .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
                .where("time", "==", booking_time.strftime("%H:%M"))

            if equipment == "IncuCyte":
                q = q.where("slot", "==", slot)

            if list(q.stream()):
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
# 📅 Advanced Calendar (color-coded + popups)
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

        # Build event title and description
        slot_text = f" – {b['slot']}" if b.get('slot') else ""
        title = f"{b['equipment']}{slot_text}"
        description = f"Booked by {b['name']} at {b['time']}"

        # Color per equipment
        color_map = {
            "IncuCyte": "#1E90FF",
            "Confocal Microscope": "#8A2BE2",
            "Flow Cytometer": "#00B894",
            "Centrifuge": "#E17055",
            "Nanodrop": "#FDCB6E",
            "Qubit 4": "#6C5CE7",
            "QuantStudio 3": "#00CEC9",
            "Genesis SC": "#FF7675",
            "Biorad ChemiDoc": "#55EFC4",
            "C1000 Touch": "#0984E3"
        }
        event_color = color_map.get(b["equipment"], "#1E90FF")

        events.append({
            "title": title,
            "start": start,
            "allDay": False,
            "backgroundColor": event_color,
            "borderColor": event_color,
            "description": description  # for popup
        })

    if events:
        calendar_options = {
            "initialView": "dayGridMonth",
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek,timeGridDay"
            },
            "height": "650px",
            "eventDisplay": "block",
            "eventClick": {
                "alert": True  # show booking details popup
            }
        }
        calendar(events, options=calendar_options)
    else:
        st.info(f"No bookings for {equipment_for_calendar}.")

except Exception as e:
    st.error(f"Error loading calendar: {e}")

# -----------------------------
# 📊 Upgraded Analytics Dashboard (with drill-down + CSV export)
# -----------------------------
import io

st.markdown("---")
st.subheader("📊 Analytics Dashboard")

# -----------------------------
# Global CSV export for all bookings
# -----------------------------
if all_bookings:
    all_rows = []
    for bk in all_bookings:
        d = bk.to_dict()
        all_rows.append([
            d.get("name", ""),
            d.get("equipment", ""),
            d.get("date", ""),
            d.get("time", ""),
            d.get("slot", "—")
        ])

    if all_rows:
        all_df = pd.DataFrame(
            all_rows,
            columns=["User", "Equipment", "Date", "Time", "Slot"]
        )
        csv_buffer = io.StringIO()
        all_df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="⬇️ Download **All Bookings (CSV)**",
            data=csv_buffer.getvalue(),
            file_name="all_bookings.csv",
            mime="text/csv"
        )

try:
    all_bookings = list(db.collection("bookings").stream())

    if not all_bookings:
        st.info("No bookings yet.")
    else:
        # Summary counts
        total_bookings = len(all_bookings)
        equipment_usage = {}
        hourly_usage = {}

        for bk in all_bookings:
            d = bk.to_dict()
            eq = d.get("equipment", "Unknown")
            equipment_usage[eq] = equipment_usage.get(eq, 0) + 1

            t = d.get("time", "00:00")
            hour = t[:2]
            hourly_usage[hour] = hourly_usage.get(hour, 0) + 1

        st.metric("Total Bookings", total_bookings)

      # Equipment usage table with drill-down + cancel option
st.markdown("### Equipment Usage")
for eq, count in sorted(equipment_usage.items(), key=lambda x: x[1], reverse=True):
    col1, col2 = st.columns([3, 1])
    col1.write(f"**{eq}:** {count} bookings")
    if col2.button(f"Details", key=f"{eq}_details"):
        st.markdown(f"#### Details for {eq}")

        # Build table data
        detailed_rows = []
        for bk in all_bookings:
            d = bk.to_dict()
            if d.get("equipment") == eq:
                detailed_rows.append({
                    "id": bk.id,
                    "name": d.get("name", ""),
                    "date": d.get("date", ""),
                    "time": d.get("time", ""),
                    "slot": d.get("slot", "—") if eq == "IncuCyte" else "—"
                })

        if detailed_rows:
            for row in detailed_rows:
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 1])
                c1.write(row["name"])
                c2.write(row["date"])
                c3.write(row["time"])
                c4.write(row["slot"])

                # Cancel button
                if c5.button("❌", key=f"cancel_{row['id']}"):
                    try:
                        db.collection("bookings").document(row["id"]).delete()
                        st.success(f"Booking for {row['name']} on {row['date']} at {row['time']} cancelled.")
                        st.experimental_rerun()
                    except Exception as e:
                        st.error(f"Error cancelling booking: {e}")
        else:
            st.info(f"No bookings found for {eq}")

        # Charts
        if equipment_usage:
            st.markdown("### Most Used Equipment (chart)")
            eq_df = pd.DataFrame(
                [{"Equipment": k, "Bookings": v} for k, v in equipment_usage.items()]
            ).sort_values("Bookings", ascending=False)
            st.bar_chart(eq_df.set_index("Equipment"))

        if hourly_usage:
            st.markdown("### Peak Booking Hours (chart)")
            hr_df = pd.DataFrame(
                [{"Hour": k, "Bookings": v} for k, v in hourly_usage.items()]
            ).sort_values("Hour")
            st.bar_chart(hr_df.set_index("Hour"))

except Exception as e:
    st.error(f"Error loading analytics: {e}")
