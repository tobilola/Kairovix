import streamlit as st
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import uuid
import os

# Load Firebase credentials securely if set
FIREBASE_KEY_PATH = "firebase_credentials.json"

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_KEY_PATH)
    firebase_admin.initialize_app(cred)

db = firestore.client()

st.set_page_config(page_title="Kairovix – Lab Scheduler", layout="centered")
st.title("🔬 Kairovix: Smart Lab Equipment Scheduler")
st.markdown("Book time slots for lab equipment in real-time. Powered by **TOBI HealthOps AI**.")

# Booking Form
with st.form("booking_form"):
    name = st.text_input("Your Name")
    equipment = st.selectbox("Select Equipment", ["IncuCyte", "Confocal Microscope", "Flow Cytometer", "Centrifuge"])
    booking_date = st.date_input("Select Date")
    booking_time = st.time_input("Select Time Slot (24h format)")
    submitted = st.form_submit_button("✅ Submit Booking")

    if submitted:
        doc_id = str(uuid.uuid4())
        booking_data = {
            "name": name,
            "equipment": equipment,
            "date": booking_date.strftime("%Y-%m-%d"),
            "time": booking_time.strftime("%H:%M"),
            "timestamp": datetime.utcnow()
        }
        db.collection("bookings").document(doc_id).set(booking_data)
        st.success(f"Booking confirmed for {equipment} at {booking_time.strftime('%H:%M')} on {booking_date.strftime('%Y-%m-%d')}")
