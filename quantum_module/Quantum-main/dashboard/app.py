
import streamlit as st
import json
from pathlib import Path

st.set_page_config(page_title="Traffic Decision Support System", layout="wide")

st.title("🚦 Pre-Event Traffic Decision Support System")
st.caption("Chepauk Stadium Scenario Planner")

# ---------------- Event ----------------

st.header("Event Configuration")

c1, c2 = st.columns(2)

with c1:
    event_name = st.text_input("Event Name", "IPL Match")
    venue = st.text_input("Venue", "MA Chidambaram Stadium")

with c2:
    date = st.date_input("Event Date")
    time = st.time_input("Event Start Time")

total = st.slider("Expected Total Vehicles", 1000, 30000, 12000)

# ---------------- Intersections ----------------

st.header("Predicted Vehicles")

j1 = st.slider("J1 Wallajah Road", 0, 5000, 1200)
j2 = st.slider("J2 Victoria Road", 0, 5000, 850)
j3 = st.slider("J3 Marina Junction", 0, 5000, 600)
j4 = st.slider("J4 Bells Road", 0, 5000, 1100)
j5 = st.slider("J5 Pycrofts Road", 0, 5000, 450)

# ---------------- Constraints ----------------

st.header("Scenario Constraints")

weather = st.selectbox(
    "Weather",
    ["Clear", "Light Rain", "Heavy Rain", "Fog"]
)

construction = st.multiselect(
    "Road Construction",
    [
        "Victoria Road",
        "Wallajah Road",
        "Bells Road"
    ]
)

vip = st.checkbox("VIP Movement")
emergency = st.checkbox("Emergency Lane")
crowd = st.checkbox("Heavy Crowd Surge")

# ---------------- Mode ----------------

mode = st.radio(
    "Optimization Mode",
    ["Classical", "Quantum"],
    horizontal=True
)

# ---------------- JSON ----------------

if st.button("Generate Scenario"):

    scenario = {
        "event": {
            "name": event_name,
            "venue": venue,
            "date": str(date),
            "start_time": str(time),
            "expected_total_vehicles": total
        },

        "intersections": {
            "J1": j1,
            "J2": j2,
            "J3": j3,
            "J4": j4,
            "J5": j5
        },

        "constraints": {
            "weather": weather,
            "construction": construction,
            "vip": vip,
            "emergency_lane": emergency,
            "crowd_surge": crowd
        },

        "optimization_mode": mode.lower()
    }

    Path("shared").mkdir(exist_ok=True)

    with open("shared/scenario_input.json", "w") as f:
        json.dump(scenario, f, indent=4)

    st.success("Scenario created.")
    st.json(scenario)