import streamlit as st
from datetime import datetime, date as date_cls
import firebase_admin
from firebase_admin import credentials, firestore, auth
import uuid
import pandas as pd
import io
from streamlit_calendar import calendar

# -----------------------------
# Firebase init
# -----------------------------
if not firebase_admin._apps:
    firebase_creds = dict(st.secrets["firebase"])
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------------
# Multi-Lab Authentication
# -----------------------------
ALLOWED_DOMAINS = {
    "adelaiogala.lab@gmail.com": "Adelaiye-Ogala Lab",
    # Add more lab emails or domains as needed
}

# 🆕 Admins: Can see all labs
ADMIN_EMAILS = [
    "youremail@example.com",  # Replace with your email
    "anotheradmin@example.com"
]

if "user_email" not in st.session_state:
    st.session_state.user_email = None
    st.session_state.lab_name = None

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Kairovix – Lab Scheduler", layout="centered")
st.title("🔬 Kairovix: Smart Lab Equipment Scheduler")
st.markdown("Book time slots for lab equipment in real-time. Powered by **TOBI HealthOps AI**.")

# -----------------------------
# Login UI
# -----------------------------
if st.session_state.user_email:
    st.success(f"Logged in as {st.session_state.user_email} ({st.session_state.lab_name})")
    if st.button("Logout"):
        st.session_state.user_email = None
        st.session_state.lab_name = None
        st.experimental_rerun()
else:
    st.warning("You must log in with your lab email to book or cancel equipment.")
    login_email = st.text_input("Lab Email Address")
    login_password = st.text_input("Password (for email login)", type="password")
    if st.button("Sign In"):
        try:
            # Validate user email
            user = auth.get_user_by_email(login_email)
            if login_email in ALLOWED_DOMAINS:
                st.session_state.user_email = login_email
                st.session_state.lab_name = ALLOWED_DOMAINS[login_email]
                st.experimental_rerun()
            else:
                st.error("❌ Your email is not authorized for this system.")
        except Exception:
            st.error("❌ Invalid login or user not found in Firebase.")

# -----------------------------
# Equipment list and slots
# -----------------------------
EQUIPMENT_LIST = [
    "IncuCyte", "Confocal Microscope", "Flow Cytometer",
    "Centrifuge", "Nanodrop", "Qubit 4", "QuantStudio 3",
    "Genesis SC", "Biorad ChemiDoc", "C1000 Touch"
]

INCUCYTE_SLOTS = [
    ["Top Left", "Top Right"],
    ["Middle Left", "Middle Right"],
    ["Bottom Left", "Bottom Right"]
]
INCUCYTE_SLOTS_FLAT = [s for row in INCUCYTE_SLOTS for s in row]

# -----------------------------
# Helper to parse 12-hour time
# -----------------------------
def _parse_datetime_12h(date_obj, time_txt):
    try:
        return datetime.strptime(
            f"{date_obj.strftime('%Y-%m-%d')} {time_txt.strip()}",
            "%Y-%m-%d %I:%M %p"
        )
    except Exception:
        return None

# -----------------------------
# Booking Form (enabled only for logged-in users)
# -----------------------------
if st.session_state.user_email:
    st.markdown(f"### Booking for {st.session_state.lab_name}")

    with st.form("booking_form"):
        name = st.text_input("Your Name")
        equipment = st.selectbox("Select Equipment", EQUIPMENT_LIST)

        start_date = st.date_input("Start Date", value=date_cls.today())
        start_time_str = st.text_input("Start Time (12hr)", placeholder="e.g. 09:00 AM")

        end_date = st.date_input("End Date", value=date_cls.today())
        end_time_str = st.text_input("End Time (12hr)", placeholder="e.g. 02:30 PM")

        slot = None
        booked_slots = set()
        available_slots = INCUCYTE_SLOTS_FLAT

        if equipment == "IncuCyte":
            st.markdown("**IncuCyte Tray — availability for the selected date/time range**")

            req_start = _parse_datetime_12h(start_date, start_time_str)
            req_end = _parse_datetime_12h(end_date, end_time_str)

            if req_start and req_end and req_start < req_end:
                same_eq_q = db.collection("bookings").where("equipment", "==", "IncuCyte").stream()

                per_slot_bookings = {s: [] for s in INCUCYTE_SLOTS_FLAT}
                for doc in same_eq_q:
                    d = doc.to_dict()
                    s = d.get("slot")
                    try:
                        b_start = _parse_datetime_12h(
                            datetime.strptime(d.get("start_date"), "%Y-%m-%d"),
                            d.get("start_time")
                        )
                        b_end = _parse_datetime_12h(
                            datetime.strptime(d.get("end_date"), "%Y-%m-%d"),
                            d.get("end_time")
                        )
                    except Exception:
                        continue
                    if s and b_start and b_end:
                        per_slot_bookings[s].append((b_start, b_end))

                for s in INCUCYTE_SLOTS_FLAT:
                    overlaps = any(not (req_end <= b_start or req_start >= b_end)
                                for (b_start, b_end) in per_slot_bookings.get(s, []))
                    if overlaps:
                        booked_slots.add(s)

                available_slots = [s for s in INCUCYTE_SLOTS_FLAT if s not in booked_slots]
            else:
                st.info("Enter valid start & end date/time to see slot availability.")

            for row in INCUCYTE_SLOTS:
                c1, c2 = st.columns(2)
                for idx, s in enumerate(row):
                    tag = "🔒 Booked" if s in booked_slots else "🟢 Available"
                    (c1 if idx == 0 else c2).markdown(f"**{s}** — {tag}")

            slot = st.radio(
                "Choose an available slot",
                options=(available_slots if available_slots else ["No slots available"]),
                index=None,
                key="incu_slot_choice"
            )

        submitted = st.form_submit_button("✅ Submit Booking")

        if submitted:
            if not name:
                st.warning("Please enter your name before submitting.")
                st.stop()

            s_dt = _parse_datetime_12h(start_date, start_time_str)
            e_dt = _parse_datetime_12h(end_date, end_time_str)
            if not s_dt or not e_dt:
                st.error("Invalid date/time format. Use HH:MM AM/PM for time.")
                st.stop()
            if s_dt >= e_dt:
                st.error("End date/time must be later than start date/time.")
                st.stop()

            if equipment == "IncuCyte" and (not slot or slot == "No slots available"):
                st.warning("Please select an available tray slot for IncuCyte.")
                st.stop()

            q = db.collection("bookings").where("equipment", "==", equipment)
            if equipment == "IncuCyte":
                q = q.where("slot", "==", slot)

            conflicts = []
            for existing in q.stream():
                d = existing.to_dict()
                try:
                    ex_start = _parse_datetime_12h(
                        datetime.strptime(d.get("start_date"), "%Y-%m-%d"),
                        d.get("start_time")
                    )
                    ex_end = _parse_datetime_12h(
                        datetime.strptime(d.get("end_date"), "%Y-%m-%d"),
                        d.get("end_time")
                    )
                except Exception:
                    continue

                if not (e_dt <= ex_start or s_dt >= ex_end):
                    conflicts.append(d)

            if conflicts:
                st.error(f"❌ {equipment} {f'({slot}) ' if slot else ''}is already booked during that period.")
            else:
                booking_data = {
                    "name": name.strip(),
                    "equipment": equipment,
                    "start_date": s_dt.strftime("%Y-%m-%d"),
                    "start_time": s_dt.strftime("%I:%M %p"),
                    "end_date": e_dt.strftime("%Y-%m-%d"),
                    "end_time": e_dt.strftime("%I:%M %p"),
                    "slot": slot if equipment == "IncuCyte" else None,
                    "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    "lab_name": st.session_state.lab_name  # 🆕 Add lab name for filtering
                }
                db.collection("bookings").document(str(uuid.uuid4())).set(booking_data)
                st.success(
                    f"✅ Booking confirmed for **{equipment}** "
                    f"{f'({slot}) ' if slot else ''}from "
                    f"{booking_data['start_date']} {booking_data['start_time']} "
                    f"to {booking_data['end_date']} {booking_data['end_time']}."
                )

else:
    st.info("🔒 You must log in with your lab email to book or cancel equipment.")

# -----------------------------
# Show Data Only if Logged In
# -----------------------------
if st.session_state.user_email:
    # -----------------------------
    # Upcoming Bookings (TABLE)
    # -----------------------------
    st.markdown("---")
    st.subheader("📋 Upcoming Bookings")

    filter_equipment = st.selectbox("Filter by Equipment", ["All"] + EQUIPMENT_LIST)
    use_date_filter = st.checkbox("Filter by a specific date")
    filter_date = st.date_input("Choose date", value=date_cls.today()) if use_date_filter else None

    rows = []
    try:
        bookings_ref = db.collection("bookings").order_by("timestamp", direction=firestore.Query.DESCENDING)

        # 🆕 Filter for non-admin users
        if st.session_state.user_email not in ADMIN_EMAILS:
            bookings_ref = bookings_ref.where("lab_name", "==", st.session_state.lab_name)

        for bk in bookings_ref.stream():
            d = bk.to_dict()
            if filter_equipment != "All" and d.get("equipment") != filter_equipment:
                continue
            if filter_date and d.get("start_date") != filter_date.strftime("%Y-%m-%d"):
                continue
            rows.append([
                d.get("name", ""),
                d.get("equipment", ""),
                d.get("slot", "") if d.get("equipment") == "IncuCyte" else "",
                d.get("start_date", ""),
                d.get("start_time", ""),
                d.get("end_date", ""),
                d.get("end_time", "")
            ])
    except Exception as e:
        st.error(f"Error loading bookings: {e}")

    if rows:
        df = pd.DataFrame(rows, columns=["Name", "Equipment", "Slot", "Start Date", "Start Time", "End Date", "End Time"])
        st.table(df)
    else:
        st.info("No bookings match your filters.")

    # -----------------------------
    # Calendar View
    # -----------------------------
    st.markdown("---")
    st.subheader("📅 Equipment-Specific Calendar")

    equipment_for_calendar = st.selectbox("Select Equipment to View", EQUIPMENT_LIST)

    try:
        bookings_ref = db.collection("bookings").where("equipment", "==", equipment_for_calendar)

        if st.session_state.user_email not in ADMIN_EMAILS:
            bookings_ref = bookings_ref.where("lab_name", "==", st.session_state.lab_name)

        events = []
        for b in bookings_ref.stream():
            d = b.to_dict()

            if not d.get("start_date") or not d.get("end_date"):
                continue
            try:
                start = datetime.strptime(d["start_date"], "%Y-%m-%d")
                end = datetime.strptime(d["end_date"], "%Y-%m-%d")
            except Exception:
                continue

            title = f"{d['equipment']} ({d['name']})"
            slot_text = f" – {d['slot']}" if d.get("slot") else ""
            events.append({
                "title": title + slot_text,
                "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "end": end.strftime("%Y-%m-%dT%H:%M:%S"),
                "allDay": False,
                "backgroundColor": "#1E90FF",
                "borderColor": "#1E90FF",
            })

        if events:
            calendar(events, options={"initialView": "dayGridMonth", "height": "600px"})
        else:
            st.info("No bookings yet.")
    except Exception as e:
        st.error(f"Error loading calendar: {e}")

    # -----------------------------
    # 📊 Analytics Dashboard (Full)
    # -----------------------------
    st.markdown("---")
    st.subheader("📊 Analytics Dashboard")

    try:
        # Fetch all bookings
        all_bookings_ref = db.collection("bookings")

        if st.session_state.user_email not in ADMIN_EMAILS:
            all_bookings_ref = all_bookings_ref.where("lab_name", "==", st.session_state.lab_name)

        all_bookings = list(all_bookings_ref.stream())

        if not all_bookings:
            st.info("No bookings yet.")
        else:
            # --- Global CSV export ---
            all_rows = []
            equipment_usage = {}
            hourly_usage = {}

            for bk in all_bookings:
                d = bk.to_dict()
                all_rows.append([
                    d.get("name", ""),
                    d.get("equipment", ""),
                    d.get("slot", "—"),
                    d.get("start_date", ""),
                    d.get("start_time", ""),
                    d.get("end_date", ""),
                    d.get("end_time", "")
                ])

                eq = d.get("equipment", "Unknown")
                equipment_usage[eq] = equipment_usage.get(eq, 0) + 1

                if d.get("start_time"):
                    hour = d["start_time"].split(":")[0]
                    hourly_usage[hour] = hourly_usage.get(hour, 0) + 1

            # CSV export button
            if all_rows:
                csv_df = pd.DataFrame(
                    all_rows,
                    columns=["User", "Equipment", "Slot", "Start Date", "Start Time", "End Date", "End Time"]
                )
                csv_buffer = io.StringIO()
                csv_df.to_csv(csv_buffer, index=False)
                st.download_button(
                    label="⬇️ Download All Bookings (CSV)",
                    data=csv_buffer.getvalue(),
                    file_name="all_bookings.csv",
                    mime="text/csv"
                )

            # Summary metrics
            st.metric("Total Bookings", len(all_bookings))

            # Equipment usage chart
            if equipment_usage:
                st.markdown("### Most Used Equipment (Chart)")
                eq_df = pd.DataFrame(
                    [{"Equipment": k, "Bookings": v} for k, v in equipment_usage.items()]
                ).sort_values("Bookings", ascending=False)
                st.bar_chart(eq_df.set_index("Equipment"))

            # Peak hours chart
            if hourly_usage:
                st.markdown("### Peak Booking Hours (Chart)")
                hr_df = pd.DataFrame(
                    [{"Hour": k, "Bookings": v} for k, v in hourly_usage.items()]
                ).sort_values("Hour")
                st.bar_chart(hr_df.set_index("Hour"))

            # --- Drill-down with cancel controls + charts ---
            st.markdown("### Equipment Usage Details")

            if "detail_eq" not in st.session_state:
                st.session_state["detail_eq"] = None

            for eq, count in sorted(equipment_usage.items(), key=lambda x: x[1], reverse=True):
                col1, col2 = st.columns([3, 1])
                col1.write(f"**{eq}:** {count} bookings")
                if col2.button("Details", key=f"{eq}_details"):
                    st.session_state["detail_eq"] = eq

            detail_eq = st.session_state.get("detail_eq")

            if detail_eq:
                st.markdown(f"#### Details for {detail_eq}")

                # Build details list
                detail_rows = []
                for b in all_bookings:
                    d = b.to_dict()
                    if d.get("equipment") != detail_eq:
                        continue
                    detail_rows.append({
                        "DocID": b.id,
                        "User": d.get("name", ""),
                        "Slot": d.get("slot", "—"),
                        "Start Date": d.get("start_date", ""),
                        "Start Time": d.get("start_time", ""),
                        "End Date": d.get("end_date", ""),
                        "End Time": d.get("end_time", "")
                    })

                if not detail_rows:
                    st.info(f"No valid bookings for {detail_eq}.")
                else:
                    ddf = pd.DataFrame(detail_rows)

                    st.markdown("##### Bookings")
                    for _, row in ddf.iterrows():
                        c1, c2, c3, c4, c5, c6 = st.columns([2.5, 2, 0.5, 2, 1.5, 0.7])
                        c1.write(row["User"])
                        c2.write(f"{row['Start Date']} {row['Start Time']}")
                        c3.write("→")
                        c4.write(f"{row['End Date']} {row['End Time']}")
                        c5.write(row["Slot"] if detail_eq == "IncuCyte" else "—")

                        # 🆕 Restrict cancel to Admin or Same Lab
                        if (st.session_state.user_email in ADMIN_EMAILS):
                            if c6.button("❌", key=f"cancel_{row['DocID']}"):
                                db.collection("bookings").document(row["DocID"]).delete()
                                st.success(f"Booking for {row['User']} cancelled.")
                                st.experimental_rerun()

                    # Charts
                    st.markdown("##### Usage Trend (Bookings over time)")
                    trend_df = (
                        ddf.groupby("Start Date").size()
                        .rename("Bookings").reset_index()
                        .sort_values("Start Date")
                    )
                    if not trend_df.empty:
                        st.line_chart(trend_df.set_index("Start Date"))

                    st.markdown("##### Start Hour Distribution")
                    hour_series = ddf["Start Time"].str.extract(r"^(\d{1,2})")[0]
                    hour_counts = (
                        hour_series.value_counts()
                        .rename_axis("Hour")
                        .rename("Bookings")
                        .sort_index()
                    )
                    if not hour_counts.empty:
                        st.bar_chart(hour_counts)

                    if detail_eq == "IncuCyte":
                        st.markdown("##### IncuCyte Slot Usage")
                        slot_counts = (
                                ddf["Slot"].replace("", "—")
                                           .value_counts()
                                           .rename_axis("Slot")
                                           .rename("Bookings")
                            )
                            if not slot_counts.empty:
                                 st.bar_chart(slot_counts)
