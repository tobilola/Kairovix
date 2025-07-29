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
# Booking form (12hr start/end, overlap check, IncuCyte slots with availability)
# -----------------------------
INCUCYTE_SLOTS = [
    ["Top Left", "Top Right"],
    ["Middle Left", "Middle Right"],
    ["Bottom Left", "Bottom Right"]
]
INCUCYTE_SLOTS_FLAT = [s for row in INCUCYTE_SLOTS for s in row]

with st.form("booking_form"):
    name = st.text_input("Your Name")
    equipment = st.selectbox("Select Equipment", EQUIPMENT_LIST)
    booking_date = st.date_input("Select Date", value=date_cls.today())

    # ---- Manual Start & End Times (12hr) ----
    st.markdown("**Enter booking times (12hr format, e.g., 09:00 AM and 02:30 PM)**")
    start_time_str = st.text_input("Start Time", placeholder="e.g. 09:00 AM")
    end_time_str   = st.text_input("End Time",   placeholder="e.g. 02:30 PM")

    # Defaults
    slot = None
    booked_slots = set()
    available_slots = INCUCYTE_SLOTS_FLAT

    # Helper: parse times safely
    def _parse_time_12h(txt):
        try:
            return datetime.strptime(txt.strip(), "%I:%M %p")
        except Exception:
            return None

    # If IncuCyte, look up which slots are booked for the chosen date AND overlapping time range
    if equipment == "IncuCyte":
        st.markdown("**IncuCyte Tray — availability for the selected date & time range**")

        # Attempt to parse the typed times so we can compute availability
        req_start = _parse_time_12h(start_time_str) if start_time_str else None
        req_end   = _parse_time_12h(end_time_str) if end_time_str else None

        if req_start and req_end and req_start < req_end:
            # Pull all IncuCyte bookings for that date
            try:
                same_day_q = db.collection("bookings") \
                    .where("equipment", "==", "IncuCyte") \
                    .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
                    .stream()

                # For each slot, see if any booking overlaps [req_start, req_end)
                per_slot_bookings = {s: [] for s in INCUCYTE_SLOTS_FLAT}
                for doc in same_day_q:
                    d = doc.to_dict()
                    s = d.get("slot")
                    s_start = _parse_time_12h(d.get("start_time", ""))
                    s_end   = _parse_time_12h(d.get("end_time", ""))

                    if s and s_start and s_end:
                        per_slot_bookings[s].append((s_start, s_end))

                # overlap if NOT (req_end <= s_start or req_start >= s_end)
                for s in INCUCYTE_SLOTS_FLAT:
                    overlaps = any(not (req_end <= s_start or req_start >= s_end)
                                   for (s_start, s_end) in per_slot_bookings.get(s, []))
                    if overlaps:
                        booked_slots.add(s)

                available_slots = [s for s in INCUCYTE_SLOTS_FLAT if s not in booked_slots]

            except Exception as e:
                st.warning(f"Could not load IncuCyte slot availability: {e}")
        else:
            st.info("Enter valid Start and End times to see slot availability.")

        # Visual grid with availability tags
        for row in INCUCYTE_SLOTS:
            c1, c2 = st.columns(2)
            for idx, s in enumerate(row):
                tag = "🔒 Booked" if s in booked_slots else "🟢 Available"
                text = f"**{s}** — {tag}"
                (c1 if idx == 0 else c2).markdown(text)

        # Selection: only from available slots
        slot = st.radio(
            "Choose an available slot",
            options=(available_slots if available_slots else ["No slots available"]),
            index=None,
            key="incu_slot_choice"
        )

    submitted = st.form_submit_button("✅ Submit Booking")

    if submitted:
        # ---- Validation ----
        if not name:
            st.warning("Please enter your name before submitting.")
            st.stop()

        # Parse/validate 12hr times
        s_time = _parse_time_12h(start_time_str)
        e_time = _parse_time_12h(end_time_str)
        if not s_time or not e_time:
            st.error("Invalid time format. Use HH:MM AM/PM, e.g., 09:00 AM.")
            st.stop()
        if not (s_time < e_time):
            st.error("End Time must be later than Start Time.")
            st.stop()

        if equipment == "IncuCyte":
            if not slot or slot == "No slots available":
                st.warning("Please select an available tray slot for IncuCyte.")
                st.stop()

        # ---- Overlap check on submit (server-side safety) ----
        day_str = booking_date.strftime("%Y-%m-%d")
        q = db.collection("bookings") \
              .where("equipment", "==", equipment) \
              .where("date", "==", day_str)

        # If IncuCyte, only compare with same slot
        if equipment == "IncuCyte":
            q = q.where("slot", "==", slot)

        conflicts = []
        for existing in q.stream():
            d = existing.to_dict()
            ex_start = _parse_time_12h(d.get("start_time", ""))
            ex_end   = _parse_time_12h(d.get("end_time", ""))
            if not ex_start or not ex_end:
                continue
            # overlap if NOT (e_time <= ex_start or s_time >= ex_end)
            if not (e_time <= ex_start or s_time >= ex_end):
                conflicts.append(d)

        if conflicts:
            if equipment == "IncuCyte":
                st.error(
                    f"❌ {equipment} **({slot})** is already booked overlapping "
                    f"{s_time.strftime('%I:%M %p')}–{e_time.strftime('%I:%M %p')} on {day_str}."
                )
            else:
                st.error(
                    f"❌ {equipment} is already booked overlapping "
                    f"{s_time.strftime('%I:%M %p')}–{e_time.strftime('%I:%M %p')} on {day_str}."
                )
        else:
            # ---- Save booking ----
            booking_data = {
                "name": name.strip(),
                "equipment": equipment,
                "date": day_str,
                "start_time": s_time.strftime("%I:%M %p"),
                "end_time":   e_time.strftime("%I:%M %p"),
                "slot": slot if equipment == "IncuCyte" else None,
                # human-readable timestamp of registration; you can also store firestore.SERVER_TIMESTAMP via Admin SDK
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            }
            db.collection("bookings").document(str(uuid.uuid4())).set(booking_data)
            st.success(
                f"✅ Booking confirmed for **{equipment}** "
                f"{f'({slot}) ' if slot else ''}"
                f"{booking_data['start_time']}–{booking_data['end_time']} on {day_str}."
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
# 📊 Full Analytics Dashboard (Global CSV + Drill-down + Cancel + Charts)
# -----------------------------
import io

st.markdown("---")
st.subheader("📊 Analytics Dashboard")

# Fetch all bookings once at the top
all_bookings = []
try:
    all_bookings = list(db.collection("bookings").stream())
except Exception as e:
    st.error(f"Error fetching bookings: {e}")

if not all_bookings:
    st.info("No bookings yet.")
else:
    # --- Global CSV export ---
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

    # --- Summary metrics ---
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

    # --- Drill-down with cancel controls ---
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

    # --- Charts ---
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
