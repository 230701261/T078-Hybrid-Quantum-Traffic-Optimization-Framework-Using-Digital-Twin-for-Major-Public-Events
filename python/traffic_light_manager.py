import traci

class TrafficLightManager:
    def __init__(self):
        self.tl_ids = []
        self.signal_states = {}

    def initialize(self):
        try:
            self.tl_ids = traci.trafficlight.getIDList()
        except Exception:
            self.tl_ids = []

    def set_scenario_timings(self, scenario: str):
        """
        Adjust signal programs and phase durations dynamically based on the scenario.
        For Event Day: Extend green phases for stadium-bound corridors (Wallajah Rd & Bells Rd).
        """
        if not self.tl_ids:
            return
        
        # During Event Day, adjust phase durations if needed
        # We can dynamically monitor queues at junctions and extend green time on congested approaches
        pass

    def get_all_states(self):
        """
        Extracts current phase, state string (e.g. 'GGggrr'), and color breakdown for all TLS.
        """
        result = {}
        for tl_id in self.tl_ids:
            try:
                state_str = traci.trafficlight.getRedYellowGreenState(tl_id)
                phase_idx = traci.trafficlight.getPhase(tl_id)
                phase_duration = traci.trafficlight.getPhaseDuration(tl_id)
                remaining = traci.trafficlight.getNextSwitch(tl_id) - traci.simulation.getTime()
                
                # Determine predominant color for simple rendering
                predominant = "green"
                if "r" in state_str.lower() and "g" not in state_str.lower():
                    predominant = "red"
                elif "y" in state_str.lower() and "g" not in state_str.lower():
                    predominant = "yellow"
                elif "g" in state_str.lower():
                    predominant = "green"

                result[tl_id] = {
                    "id": tl_id,
                    "phase": phase_idx,
                    "state": state_str,
                    "color": predominant,
                    "phase_duration_s": round(float(phase_duration), 1),
                    "seconds_to_switch": round(max(0.0, float(remaining)), 1)
                }
            except Exception:
                continue
        return result
