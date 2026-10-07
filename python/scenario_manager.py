import traci
import random
from .config import (
    TRAIN_INTERVAL_NORMAL,
    TRAIN_INTERVAL_EVENT,
    TRAIN_PASSENGER_BURST_EVENT,
    TRAIN_PASSENGER_BURST_NORMAL
)

class ScenarioManager:
    def __init__(self):
        self.current_scenario = "normal_day"
        self.crowd_counter = 0
        self.last_crowd_burst_time = 0
        self.demand_end_time_s = 3600.0

    def set_demand_end_time(self, end_time_s: float):
        self.demand_end_time_s = max(0.0, float(end_time_s))

    def set_scenario(self, scenario_name: str):
        if scenario_name in ["normal_day", "event_day"]:
            self.current_scenario = scenario_name
            self.crowd_counter = 0
            self.last_crowd_burst_time = 0

    def get_event_phase(self, sim_time: float) -> str:
        """
        Returns the current Event Day phase based on simulation clock:
        0-300s: Pre-Event Build-Up
        300-900s: Arrival Surge
        900-1500s: Peak Congestion
        1500s+: Departure Egress
        """
        if self.current_scenario == "normal_day":
            return "NORMAL DAY"
        
        if sim_time < 300.0:
            return "PRE-EVENT BUILD-UP"
        elif sim_time < 900.0:
            return "ARRIVAL SURGE"
        elif sim_time < 1500.0:
            return "PEAK CONGESTION"
        else:
            return "DEPARTURE EGRESS"

    def step(self, sim_time: float):
        """
        Scenario-specific dynamic events.
        Triggers passenger arrivals when scheduled MRTS trains stop at the single Chepauk station.
        """
        # Train passenger bursts are bounded by the configured SUMO demand
        # window. Continuing to inject persons forever kept an otherwise
        # completed vehicle simulation alive at ever-increasing sim times.
        if sim_time >= self.demand_end_time_s:
            return

        interval = TRAIN_INTERVAL_EVENT if self.current_scenario == "event_day" else TRAIN_INTERVAL_NORMAL
        
        if sim_time - self.last_crowd_burst_time >= interval:
            self.last_crowd_burst_time = sim_time
            self._dispatch_train_crowd_burst(sim_time)

    def _dispatch_train_crowd_burst(self, sim_time: float):
        """
        Generates passenger surges stepping off the single elevated MRTS station.
        Event Day: 85% walk via the dedicated orange walkway to the Stadium.
        Normal Day: Diffuse flow to Beach, Triplicane, and local destinations.
        """
        phase = self.get_event_phase(sim_time)

        if self.current_scenario == "event_day":
            batch_size = random.randint(TRAIN_PASSENGER_BURST_EVENT - 5, TRAIN_PASSENGER_BURST_EVENT + 10)
            stadium_prob = 0.88 if phase != "DEPARTURE EGRESS" else 0.15
        else:
            batch_size = random.randint(TRAIN_PASSENGER_BURST_NORMAL - 3, TRAIN_PASSENGER_BURST_NORMAL + 4)
            stadium_prob = 0.20

        for _ in range(batch_size):
            self.crowd_counter += 1
            person_id = f"train_crowd_{self.crowd_counter}_{int(sim_time)}"
            dice = random.random()
            try:
                if dice < stadium_prob:
                    # Single Station -> Elevated Stairs -> 4.5m Orange Walkway -> Stadium East Gate & Plaza
                    walk_edges = ["E_PED_STAIRS_DOWN", "E_PED_STATION_STAD", "E_PED_STAD_PLAZA"]
                    traci.person.add(person_id, "E_PED_STAIRS_DOWN", pos=random.uniform(0.5, 4.0), depart=sim_time, typeID="ped_stadium")
                    traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=20.0)
                    traci.person.setColor(person_id, (250, 204, 21, 255))  # CSK Yellow
                elif dice < stadium_prob + 0.50:
                    # Station -> Marina Beach (Via ground promenade buffer)
                    walk_edges = ["E_PED_STAIRS_DOWN", "E_PED_STATION_STAD", "E_PED_STAD_PLAZA", "E_PED_STAD_CENTRAL", "E_CENTRAL_2", "E_SOUTH_2", "E_PED_BEACH_ACCESS_S"]
                    traci.person.add(person_id, "E_PED_STAIRS_DOWN", pos=random.uniform(0.5, 4.0), depart=sim_time, typeID="ped_beach")
                    traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=30.0)
                    traci.person.setColor(person_id, (56, 189, 248, 255))  # Light Blue
                else:
                    # Station -> Local Area
                    walk_edges = ["E_PED_STAIRS_DOWN", "E_PED_STATION_STAD", "E_PED_STAD_PLAZA", "E_PED_STAD_CENTRAL", "E_CENTRAL_1_rev", "E_NORTH_1_rev"]
                    traci.person.add(person_id, "E_PED_STAIRS_DOWN", pos=random.uniform(0.5, 4.0), depart=sim_time, typeID="ped_local")
                    traci.person.appendWalkingStage(person_id, walk_edges, arrivalPos=20.0)
                    traci.person.setColor(person_id, (148, 163, 184, 255))  # Grey
            except Exception:
                pass
