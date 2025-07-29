import streamlit as st
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import uuid

# Load Firebase credentials from Streamlit secrets
if not firebase_admin._apps:
    firebase_creds = dict(st.secrets["firebase"])
    cred = credentials.Certificate(firebase_creds)
    firebase_admin.initialize_app(cred)

# Firestore client
db = firestore.client()

# Streamlit page setup
st.set_page_config(page_title="Kairovix – Lab Scheduler", layout="centered")
st.title("🔬 Kairovix: Smart Lab Equipment Scheduler")
st.markdown("Book time slots for lab equipment in real-time. Powered by **TOBI HealthOps AI**.")

# Booking Form
with st.form("booking_form"):
    name = st.text_input("Your Name")
    equipment = st.selectbox("Select Equipment", [
        "IncuCyte", "Confocal Microscope", "Flow Cytometer",
        "Centrifuge", "Nanodrop", "Qubit 4", "QuantStudio 3",
        "Genesis SC", "Biorad ChemiDoc", "C1000 Touch"
    ])
    booking_date = st.date_input("Select Date")
    booking_time = st.time_input("Select Time Slot (24h format)")
    submitted = st.form_submit_button("✅ Submit Booking")

    # 👇 Indented correctly inside the form
    if submitted:
        # Check for existing booking with same equipment, date, and time
        existing_bookings = db.collection("bookings") \
            .where("equipment", "==", equipment) \
            .where("date", "==", booking_date.strftime("%Y-%m-%d")) \
            .where("time", "==", booking_time.strftime("%H:%M")) \
            .stream()

        if any(existing_bookings):
            st.error(
                f"❌ {equipment} is already booked for "
                f"{booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}. "
                "Please choose a different slot."
            )
        else:
            doc_id = str(uuid.uuid4())
            booking_data = {
                "name": name,
                "equipment": equipment,
                "date": booking_date.strftime("%Y-%m-%d"),
                "time": booking_time.strftime("%H:%M"),
                "timestamp": datetime.utcnow()
            }
            db.collection("bookings").document(doc_id).set(booking_data)
            st.success(
                f"✅ Booking confirmed for {equipment} at "
                f"{booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}."
            )

# Optional: Add a section to view recent bookings
st.markdown("---")
if st.checkbox("📋 Show Recent Bookings"):
    bookings_ref = db.collection("bookings").order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    ).limit(10)
    bookings = bookings_ref.stream()

    for booking in bookings:
        data = booking.to_dict()
        st.markdown(
            f"🔹 **{data['equipment']}** booked by **{data['name']}** "
            f"on **{data['date']} at {data['time']}**"
        )

# Upcoming bookings table
st.markdown("---")
st.subheader("📋 Upcoming Bookings")

try:
    bookings_ref = db.collection("bookings").order_by(
        "timestamp", direction=firestore.Query.DESCENDING
    )
    bookings = bookings_ref.stream()

    data = []
    for booking in bookings:
        b = booking.to_dict()
        data.append([b["name"], b["equipment"], b["date"], b["time"]])

    if data:
        st.table(data)
    else:
        st.info("No bookings yet. Submit a booking above.")
except Exception as e:
    st.error(f"Error loading bookings: {e}")
