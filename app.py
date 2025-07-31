import streamlit as st
from datetime import datetime, date as date_cls
import firebase_admin
from firebase_admin import credentials, firestore, auth
import uuid
import pandas as pd
import io
from streamlit_calendar import calendar
import requests  # for REST login

# -----------------------------
# Firebase init (robust, PEM-safe)
# -----------------------------
def init_firebase():
    # If already initialized, reuse the existing app/client
    if firebase_admin._apps:
        return firestore.client()

    # 1) Read secrets
    try:
        fb = dict(st.secrets["firebase"])
    except Exception:
        st.error("❌ Missing [firebase] section in secrets. Add your service account + apiKey.")
        st.stop()

    # 2) Make sure the service account key is correctly formatted
    #    - Works whether the key is stored with real newlines or as '\n'
    if "private_key" in fb and isinstance(fb["private_key"], str):
        fb["private_key"] = fb["private_key"].replace("\\n", "\n").strip()

    # 3) Force the correct type
    fb["type"] = "service_account"

    # 4) Basic sanity checks to catch malformed keys early
    pk = fb.get("private_key", "")
    if not (pk.startswith("-----BEGIN PRIVATE KEY-----") and pk.endswith("-----END PRIVATE KEY-----")):
        st.error("❌ Service account private_key looks malformed. "
                 "Check that it starts with '-----BEGIN PRIVATE KEY-----' and ends with '-----END PRIVATE KEY-----'.")
        st.stop()

    # 5) Initialize Admin SDK
    try:
        cred = credentials.Certificate(fb)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"❌ Firebase initialization failed: {e}")
        st.stop()

# Initialize once and reuse
db = init_firebase()

# Optional: warn if apiKey for email/password login is missing
FIREBASE_WEB_API_KEY = st.secrets["firebase"].get("apiKey", "")
if not FIREBASE_WEB_API_KEY:
    st.warning("⚠️ Firebase Web apiKey not found in secrets. Email/password login will fail until you add it.")

# -----------------------------
# Multi-Lab Authentication
# -----------------------------
ALLOWED_DOMAINS = {
    "adelaogala.lab@gmail.com": "Adelaiye-Ogala Lab",
}
ADMIN_EMAIL = "ogunbowaleadeola@gmail.com"  # can cancel/delete bookings and view Analytics

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
# Helpers
# -----------------------------
def safe_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def firebase_login(email: str, password: str):
    """Sign in using Firebase Identity Toolkit REST API."""
    api_key = st.secrets["firebase"].get("apiKey")
    if not api_key:
        return {"error": {"message": "MISSING_API_KEY"}}
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        return {"error": {"message": f"NETWORK_ERROR: {e}"}}

def send_password_reset(email: str):
    """Send Firebase password reset email via REST API."""
    api_key = st.secrets["firebase"].get("apiKey")
    if not api_key:
        return {"error": {"message": "MISSING_API_KEY"}}
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"
    payload = {"requestType": "PASSWORD_RESET", "email": email}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        return {"error": {"message": f"NETWORK_ERROR: {e}"}}

# -----------------------------
# Login UI
# -----------------------------
if st.session_state.user_email:
    st.success(f"Logged in as {st.session_state.user_email} ({st.session_state.lab_name})")
    if st.button("Logout"):
        st.session_state.user_email = None
        st.session_state.lab_name = None
        safe_rerun()
else:
    st.warning("You must log in with your lab email to book or cancel equipment.")
    login_email = st.text_input("Lab Email Address")
    login_password = st.text_input("Password (for email login)", type="password")

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Sign In"):
            if login_email and login_password:
                result = firebase_login(login_email, login_password)
                if "idToken" in result:
                    if login_email in ALLOWED_DOMAINS or login_email == ADMIN_EMAIL:
                        st.session_state.user_email = login_email
                        st.session_state.lab_name = ALLOWED_DOMAINS.get(login_email, "Admin")
                        safe_rerun()
                    else:
                        st.error("❌ Your email is not authorized for this system.")
                else:
                    st.error(f"❌ Login failed: {result.get('error', {}).get('message', 'Unknown error')}")
            else:
                st.error("Please enter both email and password.")
    with colB:
        if st.button("Forgot Password?"):
            if login_email:
                reset = send_password_reset(login_email)
                if "error" in reset:
                    st.error(f"❌ {reset['error']['message']}")
                else:
                    st.success(f"📧 Password reset email sent to **{login_email}**")
            else:
                st.warning("Enter your email above to reset password.")

# -----------------------------
# Equipment list and slots
# -----------------------------
EQUIPMENT_LIST = [
    "IncuCyte", "Fume Hood", "Flow Cytometer",
    "Centrifuge", "Nanodrop", "Qubit 4", "QuantStudio 3",
    "Genesis SC", "Biorad ChemiDoc", "C1000 Touch"
]

# IncuCyte tray slots (grid)
INCUCYTE_SLOTS = [
    ["Top Left", "Top Right"],
    ["Middle Left", "Middle Right"],
    ["Bottom Left", "Bottom Right"]
]
INCUCYTE_SLOTS_FLAT = [s for row in INCUCYTE_SLOTS for s in row]

# Fume Hood behaves like a slotted device with two hoods
FUME_HOOD_SLOTS = ["Fume Hood 1", "Fume Hood 2"]

# For places where we show the slot column/logic
SLOT_EQUIPMENT = {"IncuCyte", "Fume Hood"}

def _parse_datetime_12h(date_obj, time_txt):
    try:
        return datetime.strptime(
            f"{date_obj.strftime('%Y-%m-%d')} {time_txt.strip()}",
            "%Y-%m-%d %I:%M %p"
        )
    except Exception:
        return None

# -----------------------------
# Collapsible Sections (Mobile-Friendly)
# -----------------------------
if st.session_state.user_email:

    # ------------------ Booking ------------------
    with st.expander("📅 Book Equipment", expanded=True):
        with st.form("booking_form"):
            name = st.text_input("Your Name")
            equipment = st.selectbox("Select Equipment", EQUIPMENT_LIST)

            start_date = st.date_input("Start Date", value=date_cls.today())
            start_time_str = st.text_input("Start Time (12hr)", placeholder="e.g. 09:00 AM")
            end_date = st.date_input("End Date", value=date_cls.today())
            end_time_str = st.text_input("End Time (12hr)", placeholder="e.g. 02:30 PM")

            slot = None
            booked_slots = set()
            available_slots = []

            # --- IncuCyte (slotted) ---
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
                                datetime.strptime(d.get("start_date"), "%Y-%m-%d"), d.get("start_time")
                            )
                            b_end = _parse_datetime_12h(
                                datetime.strptime(d.get("end_date"), "%Y-%m-%d"), d.get("end_time")
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

                # grid view
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

            # --- Fume Hood (slotted) ---
            elif equipment == "Fume Hood":
                st.markdown("**Fume Hood — choose hood for the selected date/time range**")
                req_start = _parse_datetime_12h(start_date, start_time_str)
                req_end = _parse_datetime_12h(end_date, end_time_str)

                booked_slots = set()
                available_slots = FUME_HOOD_SLOTS[:]

                if req_start and req_end and req_start < req_end:
                    try:
                        same_eq_q = db.collection("bookings").where("equipment", "==", "Fume Hood").stream()
                        per_slot_bookings = {s: [] for s in FUME_HOOD_SLOTS}
                        for doc in same_eq_q:
                            d = doc.to_dict()
                            s = d.get("slot")
                            if not s or s not in per_slot_bookings:
                                continue
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
                            if b_start and b_end:
                                per_slot_bookings[s].append((b_start, b_end))

                        for s in FUME_HOOD_SLOTS:
                            overlaps = any(not (req_end <= b_start or req_start >= b_end)
                                           for (b_start, b_end) in per_slot_bookings.get(s, []))
                            if overlaps:
                                booked_slots.add(s)
                        available_slots = [s for s in FUME_HOOD_SLOTS if s not in booked_slots]
                    except Exception as e:
                        st.warning(f"Could not load Fume Hood availability: {e}")
                else:
                    st.info("Enter valid start & end date/time to see hood availability.")

                cols = st.columns(2)
                cols[0].markdown(f"**Fume Hood 1** — {'🔒 Booked' if 'Fume Hood 1' in booked_slots else '🟢 Available'}")
                cols[1].markdown(f"**Fume Hood 2** — {'🔒 Booked' if 'Fume Hood 2' in booked_slots else '🟢 Available'}")

                slot = st.radio(
                    "Choose a hood",
                    options=(available_slots if available_slots else ["No hoods available"]),
                    index=None,
                    key="fume_hood_choice"
                )

            # non-slotted devices: no slot UI

            submitted = st.form_submit_button("✅ Submit Booking")
            if submitted:
                s_dt = _parse_datetime_12h(start_date, start_time_str)
                e_dt = _parse_datetime_12h(end_date, end_time_str)
                if not name or not s_dt or not e_dt or s_dt >= e_dt:
                    st.error("❌ Please fill all fields correctly.")
                    st.stop()

                # Require a slot for slotted equipment
                if equipment in SLOT_EQUIPMENT:
                    none_label = "No slots available" if equipment == "IncuCyte" else "No hoods available"
                    if not slot or slot == none_label:
                        st.warning(f"Please select a slot for {equipment}.")
                        st.stop()

                # conflict query, include slot for slotted equipment
                q = db.collection("bookings").where("equipment", "==", equipment)
                if equipment in SLOT_EQUIPMENT:
                    q = q.where("slot", "==", slot)

                conflicts = []
                for existing in q.stream():
                    d = existing.to_dict()
                    try:
                        ex_start = _parse_datetime_12h(
                            datetime.strptime(d.get("start_date"), "%Y-%m-%d"), d.get("start_time")
                        )
                        ex_end = _parse_datetime_12h(
                            datetime.strptime(d.get("end_date"), "%Y-%m-%d"), d.get("end_time")
                        )
                    except Exception:
                        continue
                    if not (e_dt <= ex_start or s_dt >= ex_end):
                        conflicts.append(d)

                if conflicts:
                    st.error(f"❌ {equipment} {f'({slot}) ' if slot else ''} is already booked during that period.")
                else:
                    booking_data = {
                        "name": name.strip(),
                        "equipment": equipment,
                        "start_date": s_dt.strftime("%Y-%m-%d"),
                        "start_time": s_dt.strftime("%I:%M %p"),
                        "end_date": e_dt.strftime("%Y-%m-%d"),
                        "end_time": e_dt.strftime("%I:%M %p"),
                        "slot": slot if equipment in SLOT_EQUIPMENT else None,
                        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    db.collection("bookings").document(str(uuid.uuid4())).set(booking_data)
                    st.success(f"✅ Booking confirmed for **{equipment}**")

    # ------------------ Upcoming Bookings ------------------
    with st.expander("📋 Upcoming Bookings", expanded=False):
        filter_equipment = st.selectbox("Filter by Equipment", ["All"] + EQUIPMENT_LIST)
        use_date_filter = st.checkbox("Filter by a specific date")
        filter_date = st.date_input("Choose date", value=date_cls.today()) if use_date_filter else None

        rows = []
        try:
            bookings_ref = db.collection("bookings").order_by("timestamp", direction=firestore.Query.DESCENDING)
            for bk in bookings_ref.stream():
                d = bk.to_dict()
                if filter_equipment != "All" and d.get("equipment") != filter_equipment:
                    continue
                if filter_date and d.get("start_date") != filter_date.strftime("%Y-%m-%d"):
                    continue
                rows.append([
                    d.get("name", ""),
                    d.get("equipment", ""),
                    d.get("slot", "") if d.get("equipment") in SLOT_EQUIPMENT else "",
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

    # ------------------ Calendar ------------------
    with st.expander("📅 Equipment-Specific Calendar", expanded=False):
        equipment_for_calendar = st.selectbox("Select Equipment to View", EQUIPMENT_LIST)
        try:
            bookings_ref = db.collection("bookings").where("equipment", "==", equipment_for_calendar)
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
# 📊 Analytics Dashboard (ADMIN ONLY)
# -----------------------------
if st.session_state.user_email == ADMIN_EMAIL:
    with st.expander("📊 Analytics Dashboard (Admin)", expanded=False):
        try:
            # 1) Pull all bookings once
            snapshots = list(db.collection("bookings").stream())
            if not snapshots:
                st.info("No bookings yet.")
            else:
                # 2) Build a dataframe that INCLUDES DocID for deletes
                rows = []
                equipment_usage = {}
                hourly_usage = {}

                for doc in snapshots:
                    d = doc.to_dict()
                    rows.append({
                        "DocID": doc.id,
                        "User": d.get("name", ""),
                        "Equipment": d.get("equipment", ""),
                        "Slot": d.get("slot", "—"),
                        "Start Date": d.get("start_date", ""),
                        "Start Time": d.get("start_time", ""),
                        "End Date": d.get("end_date", ""),
                        "End Time": d.get("end_time", "")
                    })

                    eq = d.get("equipment", "Unknown")
                    equipment_usage[eq] = equipment_usage.get(eq, 0) + 1

                    if d.get("start_time"):
                        hour = d["start_time"].split(":")[0]
                        hourly_usage[hour] = hourly_usage.get(hour, 0) + 1

                df = pd.DataFrame(rows)
                filtered_df = df  # (apply filters later if needed)

                # 3) CSV export
                if not df.empty:
                    csv_buffer = io.StringIO()
                    df.to_csv(csv_buffer, index=False)
                    st.download_button(
                        "⬇️ Download All Bookings (CSV)",
                        csv_buffer.getvalue(),
                        "all_bookings.csv",
                        mime="text/csv"
                    )

                # 4) Summary & charts
                st.metric("Total Bookings", len(df))

                if equipment_usage:
                    st.markdown("### Most Used Equipment (Chart)")
                    eq_df = pd.DataFrame(
                        [{"Equipment": k, "Bookings": v} for k, v in equipment_usage.items()]
                    ).sort_values("Bookings", ascending=False)
                    st.bar_chart(eq_df.set_index("Equipment"))

                if hourly_usage:
                    st.markdown("### Peak Booking Hours (Chart)")
                    hr_df = pd.DataFrame(
                        [{"Hour": k, "Bookings": v} for k, v in hourly_usage.items()]
                    ).sort_values("Hour")
                    st.bar_chart(hr_df.set_index("Hour"))

                # 5) --- Drill-down details with admin-only delete ---
                st.markdown("### Equipment Usage Details")

                required_cols = {"DocID", "User", "Equipment", "Start Date", "Start Time", "End Date", "End Time", "Slot"}
                missing_cols = required_cols - set(filtered_df.columns)
                if missing_cols:
                    st.warning("Some expected columns are missing from analytics data: " + ", ".join(sorted(missing_cols)))

                if "detail_eq" not in st.session_state:
                    st.session_state["detail_eq"] = None

                for eq in sorted(filtered_df["Equipment"].dropna().unique()):
                    eq_count = len(filtered_df[filtered_df["Equipment"] == eq])
                    col1, col2 = st.columns([3, 1])
                    col1.write(f"**{eq}:** {eq_count} bookings")
                    if col2.button("Details", key=f"{eq}_details"):
                        st.session_state["detail_eq"] = eq

                detail_eq = st.session_state.get("detail_eq")
                if detail_eq:
                    st.markdown(f"#### Details for {detail_eq}")

                    detail_rows = filtered_df[filtered_df["Equipment"] == detail_eq].copy()
                    if detail_rows.empty:
                        st.info(f"No valid bookings for {detail_eq}.")
                    else:
                        for row in detail_rows.itertuples(index=False):
                            c1, c2, c3, c4, c5, c6 = st.columns([2.5, 2, 0.5, 2, 1.5, 0.9])
                            c1.write(getattr(row, "User", ""))
                            c2.write(f"{getattr(row, 'Start Date', '')} {getattr(row, 'Start Time', '')}")
                            c3.write("→")
                            c4.write(f"{getattr(row, 'End Date', '')} {getattr(row, 'End Time', '')}")
                            slot_val = getattr(row, "Slot", "—")
                            c5.write(slot_val if (detail_eq in SLOT_EQUIPMENT and pd.notna(slot_val) and str(slot_val).strip()) else "—")

                            if st.session_state.user_email == ADMIN_EMAIL:
                                doc_id = getattr(row, "DocID", None)
                                if doc_id:
                                    if c6.button("❌ Delete", key=f"delete_{doc_id}"):
                                        try:
                                            db.collection("bookings").document(doc_id).delete()
                                            st.success(f"✅ Deleted booking for {getattr(row, 'User', '')}.")
                                            safe_rerun()
                                        except Exception as e:
                                            st.error(f"Delete failed: {e}")
                                else:
                                    c6.write("—")
                            else:
                                c6.write("🔒")

                # Slot/Hood usage chart for slotted equipment
                if detail_eq in SLOT_EQUIPMENT:
                    st.markdown(f"##### {detail_eq} Slot / Hood Usage")
                    slot_counts = (
                        filtered_df[filtered_df["Equipment"] == detail_eq]["Slot"]
                        .replace("", "—")
                        .value_counts()
                        .rename_axis("Slot")
                        .rename("Bookings")
                    )
                    if not slot_counts.empty:
                        st.bar_chart(slot_counts)

        except Exception as e:
            st.error(f"Error loading analytics: {e}")

else:
    # logged-in but not admin: keep the gentle note
    if st.session_state.user_email:
        st.info("🔒 Analytics is restricted to admin users.")
    else:
        st.info("🔒 You must log in with your lab email to access bookings and analytics.")

# -----------------------------
# Footer
# -----------------------------
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity:0.8;'>Powered by <b>TOBI HealthOps AI</b></div>",
    unsafe_allow_html=True,
)
