
"""
scenario_profiles.py

Central library of scenario effects.

Every optimization module reads these values
instead of hardcoding weather logic.
"""

SCENARIO_PROFILES = {

    "Clear": {

        "capacity_multiplier": 1.00,

        "speed_multiplier": 1.00,

        "safety_risk": 0.00
    },

    "Light Rain": {

        "capacity_multiplier": 0.90,

        "speed_multiplier": 0.80,

        "safety_risk": 0.15
    },

    "Heavy Rain": {

        "capacity_multiplier": 0.75,

        "speed_multiplier": 0.63,

        "safety_risk": 0.50
    },

    "Fog": {

        "capacity_multiplier": 0.85,

        "speed_multiplier": 0.70,

        "safety_risk": 0.30
    }
}

SPECIAL_CONDITIONS = {

    "construction": {

        "capacity_multiplier": 0.60,

        "description": "Lane closures reduce capacity."
    },

    "vip": {

        "capacity_multiplier": 0.80,

        "description": "VIP security creates temporary restrictions."
    },

    "crowd_surge": {

        "capacity_multiplier": 0.90,

        "description": "Pedestrian crossing delays traffic."
    },

    "parking_overflow": {

        "capacity_multiplier": 0.85,

        "description": "Parking search increases congestion."
    }
}