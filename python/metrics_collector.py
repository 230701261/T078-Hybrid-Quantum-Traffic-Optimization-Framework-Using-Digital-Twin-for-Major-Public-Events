"""Measured SUMO telemetry aggregates; never seed live panels with demo values."""

from collections import deque
from typing import Iterable

import numpy as np


class MetricsCollector:
    def __init__(self, max_history: int = 120):
        self.max_history = max_history
        self.reset()

    def reset(self):
        self.history_time = deque(maxlen=self.max_history)
        self.history_speed = deque(maxlen=self.max_history)
        self.history_waiting = deque(maxlen=self.max_history)
        self.history_vehicles = deque(maxlen=self.max_history)
        self.history_pedestrians = deque(maxlen=self.max_history)
        self.history_congestion = deque(maxlen=self.max_history)
        self.arrival_window = deque()
        self.completed_vehicles = 0
        self.total_completed_travel_time_s = 0.0
        self.total_completed_accumulated_waiting_s = 0.0
        self.cumulative_stadium_visitors = 0
        self.cumulative_railway_arrivals = 0
        self.stadium_pedestrian_ids = set()
        self.railway_pedestrian_ids = set()
        self.live_kpis = {
            "time_s": 0.0,
            "active_vehicles": 0,
            "active_pedestrians": 0,
            "active_buses": 0,
            "avg_speed_kmh": None,
            "avg_waiting_time_s": None,
            "accumulated_waiting_time_s": 0.0,
            "total_queue_length_m": 0.0,
            "overall_congestion_pct": None,
            "completed_vehicles": 0,
            "total_completed_travel_time_s": 0.0,
            "avg_completed_travel_time_s": None,
            "completed_accumulated_waiting_time_s": 0.0,
            "throughput_vehicles_per_hour": 0.0,
            "stadium_visitors_total": 0,
            "railway_arrivals_total": 0,
        }

    def update(self, sim_time, vehicles, pedestrians, edges_congestion, current_scenario,
               arrived_trip_times: Iterable[float] = (), arrived_waiting_times: Iterable[float] = ()):
        del current_scenario  # Scenario is metadata, not a source of seeded performance values.
        arrived_trip_times = list(arrived_trip_times)
        arrived_waiting_times = list(arrived_waiting_times)
        veh_count = len(vehicles)
        ped_count = len(pedestrians)
        bus_count = sum(1 for v in vehicles if v.get("type") == "bus")
        speeds = [float(v["speed"]) * 3.6 for v in vehicles if v.get("speed") is not None]
        avg_speed = float(np.mean(speeds)) if speeds else None
        current_waits = [float(v.get("waiting_time", 0.0)) for v in vehicles]
        avg_waiting = float(np.mean(current_waits)) if current_waits else None
        accumulated_waiting = sum(float(v.get("accumulated_waiting_time", 0.0)) for v in vehicles)
        total_queue = sum(float(e["queue_len"]) for e in edges_congestion.values())
        congestion_values = [float(e["occupancy"]) * 100 for e in edges_congestion.values()]
        overall_congestion = float(np.mean(congestion_values)) if congestion_values else None

        self.completed_vehicles += len(arrived_trip_times)
        self.total_completed_travel_time_s += sum(arrived_trip_times)
        self.total_completed_accumulated_waiting_s += sum(arrived_waiting_times)
        for _ in arrived_trip_times:
            self.arrival_window.append(float(sim_time))
        while self.arrival_window and sim_time - self.arrival_window[0] > 300.0:
            self.arrival_window.popleft()
        observed_window = min(300.0, max(0.0, float(sim_time)))
        throughput = (len(self.arrival_window) / observed_window * 3600.0
                      if observed_window > 0.0 else None)

        for pedestrian in pedestrians:
            p_id, p_edge = pedestrian["id"], pedestrian.get("edge_id", "")
            if "STAD" in p_edge and p_id not in self.stadium_pedestrian_ids:
                self.stadium_pedestrian_ids.add(p_id)
                self.cumulative_stadium_visitors += 1
            if ("STATION" in p_edge or "RS_" in p_edge) and p_id not in self.railway_pedestrian_ids:
                self.railway_pedestrian_ids.add(p_id)
                self.cumulative_railway_arrivals += 1

        self.live_kpis = {
            "time_s": round(sim_time, 1),
            "active_vehicles": veh_count,
            "active_pedestrians": ped_count,
            "active_buses": bus_count,
            "avg_speed_kmh": round(avg_speed, 1) if avg_speed is not None else None,
            "avg_waiting_time_s": round(avg_waiting, 1) if avg_waiting is not None else None,
            "accumulated_waiting_time_s": round(accumulated_waiting, 1),
            "total_queue_length_m": round(total_queue, 1),
            "overall_congestion_pct": round(min(100.0, overall_congestion), 1) if overall_congestion is not None else None,
            "completed_vehicles": self.completed_vehicles,
            "total_completed_travel_time_s": round(self.total_completed_travel_time_s, 1),
            "avg_completed_travel_time_s": (round(self.total_completed_travel_time_s / self.completed_vehicles, 1)
                                             if self.completed_vehicles else None),
            "completed_accumulated_waiting_time_s": round(self.total_completed_accumulated_waiting_s, 1),
            "throughput_vehicles_per_hour": round(throughput, 1) if throughput is not None else None,
            "stadium_visitors_total": self.cumulative_stadium_visitors,
            "railway_arrivals_total": self.cumulative_railway_arrivals,
        }
        self.history_time.append(round(sim_time, 1))
        self.history_speed.append(round(avg_speed, 1) if avg_speed is not None else None)
        self.history_waiting.append(round(avg_waiting, 1) if avg_waiting is not None else None)
        self.history_vehicles.append(veh_count)
        self.history_pedestrians.append(ped_count)
        self.history_congestion.append(round(overall_congestion, 1) if overall_congestion is not None else None)

    def get_chart_data(self):
        return {
            "timestamps": list(self.history_time),
            "speed": list(self.history_speed),
            "waiting": list(self.history_waiting),
            "vehicles": list(self.history_vehicles),
            "pedestrians": list(self.history_pedestrians),
            "congestion": list(self.history_congestion),
        }

    def get_comparison(self):
        """Return only current measured aggregates; unavailable values stay null."""
        return dict(self.live_kpis)
