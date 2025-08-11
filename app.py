# app.py
import streamlit as st
from datetime import datetime, date as date_cls
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import pandas as pd
import io
from streamlit_calendar import calendar
import requests  # Firebase Auth (REST)

# =============================
# Firebase init (robust, PEM-safe)
# =============================
def init_firebase():
    if firebase_admin._apps:
        return firestore.client()

    try:
        fb = dict(st.secrets["firebase"])
    except Exception:
        st.error("❌ Missing [firebase] section in secrets. Add your service account JSON + apiKey.")
        st.stop()

    # normalize private key
    if "private_key" in fb and isinstance(fb["private_key"], str):
        fb["private_key"] = fb["private_key"].replace("\\n", "\n").strip()

    fb["type"] = "service_account"

    pk = fb.get("private_key", "")
    if not (pk.startswith("-----BEGIN PRIVATE KEY-----") and pk.endswith("-----END PRIVATE KEY-----")):
        st.error("❌ Service account private_key looks malformed. Ensure BEGIN/END lines are correct.")
        st.stop()

    try:
        cred = credentials.Certificate(fb)
        firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"❌ Firebase initialization failed: {e}")
        st.stop()

db = init_firebase()

# Optional: warn if apiKey for email/password login is missing
FIREBASE_WEB_API_KEY = st.secrets["firebase"].get("apiKey", "")
if not FIREBASE_WEB_API_KEY:
    st.warning("⚠️ Firebase Web apiKey not found in secrets. Email/password login & signup will fail until you add it.")

# =============================
# App configuration
# =============================
st.set_page_config(page_title="Kairovix – Lab Scheduler", layout="centered")
st.title("🔬 Kairovix: Smart Lab Equipment Scheduler")
st.markdown("Book time slots for lab equipment in real time.")

# Admin + lab settings
ADMIN_EMAIL = "ogunbowaleadeola@gmail.com"

# Known single-email → lab name
KNOWN_LABS = {
    "adelaogala.lab@gmail.com": "Adelaiye-Ogala Lab",
}

# Domain → default lab assignment (multi-lab support)
DOMAIN_TO_LAB = {
    "@buffalo.edu": "Adelaiye-Ogala Lab",
    # add more domains → labs as needed, e.g. "@mylab.org": "My Lab"
}

# Session state
if "user_email" not in st.session_state:
    st.session_state.user_email = None
    st.session_state.lab_name = None

# =============================
# Helpers
# =============================
def safe_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

def _parse_datetime_12h(date_obj, time_txt):
    try:
        return datetime.strptime(
            f"{date_obj.strftime('%Y-%m-%d')} {time_txt.strip()}",
            "%Y-%m-%d %I:%M %p"
        )
    except Exception:
        return None

def _infer_lab_from_email(email: str) -> str:
    if email in KNOWN_LABS:
        return KNOWN_LABS[email]
    for dom, lab in DOMAIN_TO_LAB.items():
        if email.lower().endswith(dom):
            return lab
    return "Unassigned"

# ----- Firebase Auth (REST) -----
def firebase_login(email: str, password: str):
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

def firebase_signup(email: str, password: str):
    api_key = st.secrets["firebase"].get("apiKey")
    if not api_key:
        return {"error": {"message": "MISSING_API_KEY"}}
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    try:
        resp = requests.post(url, json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        return {"error": {"message": f"NETWORK_ERROR: {e}"}}

def send_password_reset(email: str):
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

# =============================
# Equipment & slots
# =============================
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

# Fume Hood slots
FUME_HOOD_SLOTS = ["Fume Hood 1", "Fume Hood 2"]

# Which equipment uses slot logic
SLOT_EQUIPMENT = {"IncuCyte", "Fume Hood"}

# =============================
# Auth UI
# =============================
if st.session_state.user_email:
    st.success(f"Logged in as {st.session_state.user_email} ({st.session_state.lab_name})")
    # Let users adjust their lab (in case of "Unassigned" or multi-lab membership)
    with st.expander("Profile / Lab"):
        current_lab = st.session_state.lab_name or "Unassigned"
        new_lab = st.text_input("Your Lab Name", value=current_lab, help="Set or correct your lab name.")
        if st.button("Save Lab"):
            st.session_state.lab_name = new_lab.strip() or "Unassigned"
            st.success("Saved.")
    if st.button("Logout"):
        st.session_state.user_email = None
        st.session_state.lab_name = None
        safe_rerun()
else:
    st.warning("Log in or sign up to book equipment.")
    login_email = st.text_input("Email")
    login_password = st.text_input("Password", type="password")

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Sign In"):
            if login_email and login_password:
                result = firebase_login(login_email, login_password)
                if "idToken" in result:
                    # Allow: known emails, admin, or anyone with a domain we map (e.g., @buffalo.edu)
                    inferred_lab = _infer_lab_from_email(login_email)
                    st.session_state.user_email = login_email
                    st.session_state.lab_name = KNOWN_LABS.get(login_email, inferred_lab)
                    safe_rerun()
                else:
                    st.error(f"❌ Login failed: {result.get('error', {}).get('message', 'Unknown error')}")
            else:
                st.error("Please enter both email and password.")
    with c2:
        if st.button("Forgot Password"):
            if login_email:
                reset = send_password_reset(login_email)
                if "error" in reset:
                    st.error(f"❌ {reset['error']['message']}")
                else:
                    st.success(f"📧 Password reset email sent to **{login_email}**")
            else:
                st.warning("Enter your email above to reset password.")
    with c3:
        if st.button("Create Account"):
            if login_email and login_password:
                result = firebase_signup(login_email, login_password)
                if "idToken" in result:
                    inferred_lab = _infer_lab_from_email(login_email)
                    st.session_state.user_email = login_email
                    st.session_state.lab_name = KNOWN_LABS.get(login_email, inferred_lab)
                    st.success("🎉 Account created & logged in.")
                    safe_rerun()
                else:
                    st.error(f"❌ Signup failed: {result.get('error', {}).get('message', 'Unknown error')}")
            else:
                st.error("Enter email + password to sign up.")

# =============================
# Collapsible sections
# =============================
if st.session_state.user_email:
    # -------- Booking --------
    with st.expander("📅 Book Equipment", expanded=True):
        with st.form("booking_form"):
            name = st.text_input("Your Name")
            # Ensure we have a lab for the booking
            lab_for_booking = st.text_input("Your Lab", value=st.session_state.lab_name or "", help="Required for multi-lab usage.")
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
                st.markdown("**IncuCyte Tray — availability**")
                req_start = _parse_datetime_12h(start_date, start_time_str)
                req_end = _parse_datetime_12h(end_date, end_time_str)

                if req_start and req_end and req_start < req_end:
                    same_eq_q = db.collection("bookings").where("equipment", "==", "IncuCyte").stream()
                    per_slot_bookings = {s: [] for s in INCUCYTE_SLOTS_FLAT}
                    for doc in same_eq_q:
                        d = doc.to_dict()
                        s = d.get("slot")
                        try:
                            b_start = _parse_datetime_12h(datetime.strptime(d.get("start_date"), "%Y-%m-%d"), d.get("start_time"))
                            b_end = _parse_datetime_12h(datetime.strptime(d.get("end_date"), "%Y-%m-%d"), d.get("end_time"))
                        except Exception:
                            continue
                        if s and b_start and b_end:
                            per_slot_bookings[s].append((b_start, b_end))

                    for s in INCUCYTE_SLOTS_FLAT:
                        overlaps = any(not (req_end <= b_start or req_start >= b_end) for (b_start, b_end) in per_slot_bookings.get(s, []))
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
                    key="incu_slot_choice",
                )

            # --- Fume Hood (slotted) ---
            elif equipment == "Fume Hood":
                st.markdown("**Fume Hood — choose a hood**")
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
                                b_start = _parse_datetime_12h(datetime.strptime(d.get("start_date"), "%Y-%m-%d"), d.get("start_time"))
                                b_end = _parse_datetime_12h(datetime.strptime(d.get("end_date"), "%Y-%m-%d"), d.get("end_time"))
                            except Exception:
                                continue
                            if b_start and b_end:
                                per_slot_bookings[s].append((b_start, b_end))

                        for s in FUME_HOOD_SLOTS:
                            overlaps = any(not (req_end <= b_start or req_start >= b_end) for (b_start, b_end) in per_slot_bookings.get(s, []))
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
                    key="fume_hood_choice",
                )

            # Non-slotted equipment: nothing extra

            submitted = st.form_submit_button("✅ Submit Booking")
            if submitted:
                s_dt = _parse_datetime_12h(start_date, start_time_str)
                e_dt = _parse_datetime_12h(end_date, end_time_str)

                if not name or not lab_for_booking.strip():
                    st.error("❌ Name and Lab are required.")
                    st.stop()
                if not s_dt or not e_dt or s_dt >= e_dt:
                    st.error("❌ Please enter valid start/end times.")
                    st.stop()

                if equipment in SLOT_EQUIPMENT:
                    none_label = "No slots available" if equipment == "IncuCyte" else "No hoods available"
                    if not slot or slot == none_label:
                        st.warning(f"Please select a slot for {equipment}.")
                        st.stop()

                # Double-booking check (respect slot for slotted equipment)
                q = db.collection("bookings").where("equipment", "==", equipment)
                if equipment in SLOT_EQUIPMENT:
                    q = q.where("slot", "==", slot)

                conflicts = []
                for existing in q.stream():
                    d = existing.to_dict()
                    try:
                        ex_start = _parse_datetime_12h(datetime.strptime(d.get("start_date"), "%Y-%m-%d"), d.get("start_time"))
                        ex_end = _parse_datetime_12h(datetime.strptime(d.get("end_date"), "%Y-%m-%d"), d.get("end_time"))
                    except Exception:
                        continue
                    if not (e_dt <= ex_start or s_dt >= ex_end):
                        conflicts.append(d)

                if conflicts:
                    st.error(f"❌ {equipment} {f'({slot}) ' if slot else ''}is already booked during that period.")
                else:
                    booking_data = {
                        "name": name.strip(),
                        "email": st.session_state.user_email,
                        "lab": lab_for_booking.strip(),
                        "equipment": equipment,
                        "start_date": s_dt.strftime("%Y-%m-%d"),
                        "start_time": s_dt.strftime("%I:%M %p"),
                        "end_date": e_dt.strftime("%Y-%m-%d"),
                        "end_time": e_dt.strftime("%I:%M %p"),
                        "slot": slot if equipment in SLOT_EQUIPMENT else None,
                        "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    db.collection("bookings").document(str(uuid.uuid4())).set(booking_data)
                    st.success(f"✅ Booking confirmed for **{equipment}**")

    # -------- Upcoming Bookings --------
    with st.expander("📋 Upcoming Bookings", expanded=False):
        # Non-admins default to their lab only; admin can toggle "All labs"
        show_all_labs = False
        if st.session_state.user_email == ADMIN_EMAIL:
            show_all_labs = st.checkbox("Show all labs", value=True)
        my_lab_only = not show_all_labs

        filter_equipment = st.selectbox("Filter by Equipment", ["All"] + EQUIPMENT_LIST)
        use_date_filter = st.checkbox("Filter by a specific date")
        filter_date = st.date_input("Choose date", value=date_cls.today()) if use_date_filter else None

        rows = []
        try:
            bookings_ref = db.collection("bookings").order_by("timestamp", direction=firestore.Query.DESCENDING)
            for bk in bookings_ref.stream():
                d = bk.to_dict()
                # lab filter
                if my_lab_only and (d.get("lab", "") != (st.session_state.lab_name or "")):
                    continue
                # equipment filter
                if filter_equipment != "All" and d.get("equipment") != filter_equipment:
                    continue
                # date filter
                if filter_date and d.get("start_date") != filter_date.strftime("%Y-%m-%d"):
                    continue

                rows.append([
                    d.get("name", ""),
                    d.get("lab", ""),
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
            df = pd.DataFrame(rows, columns=["Name", "Lab", "Equipment", "Slot", "Start Date", "Start Time", "End Date", "End Time"])
            st.table(df)
        else:
            st.info("No bookings match your filters.")

    # -------- Calendar --------
    with st.expander("📅 Equipment-Specific Calendar", expanded=False):
        equipment_for_calendar = st.selectbox("Select Equipment to View", EQUIPMENT_LIST)
        try:
            bookings_ref = db.collection("bookings").where("equipment", "==", equipment_for_calendar)
            events = []
            for b in bookings_ref.stream():
                d = b.to_dict()

                # Only show same-lab events for non-admins
                if st.session_state.user_email != ADMIN_EMAIL:
                    if d.get("lab", "") != (st.session_state.lab_name or ""):
                        continue

                if not d.get("start_date") or not d.get("end_date"):
                    continue
                try:
                    start = datetime.strptime(d["start_date"], "%Y-%m-%d")
                    end = datetime.strptime(d["end_date"], "%Y-%m-%d")
                except Exception:
                    continue

                title = f"{d['equipment']} ({d.get('name','')})"
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

# =============================
# Analytics (Admin only)
# =============================
if st.session_state.user_email == ADMIN_EMAIL:
    with st.expander("📊 Analytics Dashboard (Admin)", expanded=False):
        try:
            snapshots = list(db.collection("bookings").stream())
            if not snapshots:
                st.info("No bookings yet.")
            else:
                rows = []
                equipment_usage = {}
                hourly_usage = {}

                for doc in snapshots:
                    d = doc.to_dict()
                    rows.append({
                        "DocID": doc.id,
                        "User": d.get("name", ""),
                        "Email": d.get("email", ""),
                        "Lab": d.get("lab", ""),
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

                # Filters
                labs = ["All"] + sorted([x for x in df["Lab"].dropna().unique()])
                selected_lab = st.selectbox("Filter by Lab", labs)
                if selected_lab != "All":
                    filtered_df = df[df["Lab"] == selected_lab].copy()
                else:
                    filtered_df = df.copy()

                # CSV export
                if not filtered_df.empty:
                    csv_buffer = io.StringIO()
                    filtered_df.to_csv(csv_buffer, index=False)
                    st.download_button(
                        "⬇️ Download Bookings (filtered CSV)",
                        csv_buffer.getvalue(),
                        "bookings_filtered.csv",
                        mime="text/csv"
                    )

                st.metric("Total Bookings", len(filtered_df))

                if equipment_usage:
                    st.markdown("### Most Used Equipment (Chart)")
                    eq_df = (
                        filtered_df["Equipment"]
                        .value_counts()
                        .rename_axis("Equipment")
                        .rename("Bookings")
                        .reset_index()
                    )
                    if not eq_df.empty:
                        st.bar_chart(eq_df.set_index("Equipment"))

                if hourly_usage:
                    st.markdown("### Peak Booking Hours (Chart)")
                    hr_df = (
                        filtered_df["Start Time"]
                        .str.extract(r"^(\d{1,2})")[0]
                        .value_counts()
                        .rename_axis("Hour")
                        .rename("Bookings")
                        .sort_index()
                    )
                    if not hr_df.empty:
                        st.bar_chart(hr_df)

                # Drill-down + delete
                st.markdown("### Equipment Usage Details")
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
                            c1, c2, c3, c4, c5, c6 = st.columns([2.4, 2, 0.5, 2, 1.5, 1])
                            c1.write(f"{getattr(row, 'User', '')} — {getattr(row, 'Lab', '')}")
                            c2.write(f"{getattr(row, 'Start Date', '')} {getattr(row, 'Start Time', '')}")
                            c3.write("→")
                            c4.write(f"{getattr(row, 'End Date', '')} {getattr(row, 'End Time', '')}")
                            slot_val = getattr(row, "Slot", "—")
                            show_slot = (detail_eq in SLOT_EQUIPMENT) and pd.notna(slot_val) and str(slot_val).strip()
                            c5.write(slot_val if show_slot else "—")

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

                # Optional: Slot/Hood usage chart for a selected equipment
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
    if st.session_state.user_email:
        st.info("🔒 Analytics is restricted to admin users.")
    else:
        st.info("🔒 You must log in with your lab email to access bookings and analytics.")

# =============================
# Footer
# =============================
st.markdown("---")
st.markdown(
    "<div style='text-align:center; opacity:0.8;'>Powered by <b>TOBI HealthOps AI</b></div>",
    unsafe_allow_html=True,
)
