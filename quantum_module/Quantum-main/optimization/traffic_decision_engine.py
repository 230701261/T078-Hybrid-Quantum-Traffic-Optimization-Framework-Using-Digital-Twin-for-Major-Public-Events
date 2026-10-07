"""
traffic_decision_engine.py

Converts optimization bitstrings into realistic traffic actions.

Outputs:
    results/final_traffic_plan.json

Run:
    python optimization/traffic_decision_engine.py
"""

from pathlib import Path
import json

BASE = Path(__file__).resolve().parent.parent

RESULTS = BASE / "results"

QAOA_FILE = RESULTS / "qaoa_solution.json"
CLASSICAL_FILE = RESULTS / "classical_solution.json"

OUTPUT = RESULTS / "final_traffic_plan.json"

# ---------------------------------------------------
# Scenario
# ---------------------------------------------------

EVENT = {
    "name": "IPL Match",
    "venue": "MA Chidambaram Stadium",
    "total_vehicles": 9515
}

WEATHER = "Heavy Rain"

# Corridor -> demand
CORRIDORS = [
    ("Anna Salai",1200),
    ("Triplicane High Road",1447),
    ("Wallajah Road",1100),
    ("Kamarajar Salai",600)
]

AVG_CAPACITY = 428

# Signal mapping
SIGNALS = [
    "J1","J2","J3","J4","J5",
    "J6","J7","J8","J9","J10"
]

# ---------------------------------------------------
# Load optimizer
# ---------------------------------------------------

def load_solution():

    if QAOA_FILE.exists():

        with open(QAOA_FILE) as f:
            data=json.load(f)

        return "Quantum",data

    with open(CLASSICAL_FILE) as f:
        data=json.load(f)

    return "Classical",data

# ---------------------------------------------------
# Decode bitstring
# ---------------------------------------------------

def build_plan(solution_override=None, optimizer_override=None):

    if solution_override is None:
        optimizer,data=load_solution()
    else:
        optimizer=optimizer_override or solution_override.get("mode", "Unknown")
        data=solution_override

    bitstring=data["bitstring"]
    bits=[int(b) for b in bitstring]

    # ---------------------------------------------
    # Corridors
    # ---------------------------------------------

    corridor_output=[]

    total_rerouted=0

    for i,(name,demand) in enumerate(CORRIDORS):

        enabled=bits[i]==1

        pressure=demand/AVG_CAPACITY

        overflow=max(0,demand-AVG_CAPACITY)

        rerouted=0

        if enabled:

            rerouted=min(
                int(overflow*0.25),
                85
            )

        remaining=max(0,overflow-rerouted)

        total_rerouted+=rerouted

        corridor_output.append({

            "corridor":name,
            "enabled":enabled,
            "demand":demand,
            "capacity":AVG_CAPACITY,
            "pressure":round(pressure,2),
            "overflow":overflow,
            "rerouted":rerouted,
            "remaining_queue":remaining
        })

    # ---------------------------------------------
    # Signals
    # ---------------------------------------------

    signal_output=[]

    active_signals=0

    for i,junction in enumerate(SIGNALS,start=4):

        enabled=bits[i]==1

        if not enabled:
            continue

        active_signals+=1

        old_green=25

        increase=min(
            15,
            max(5,active_signals*3)
        )

        signal_output.append({

            "junction":junction,
            "old_green":old_green,
            "new_green":old_green+increase,
            "extra_green":increase
        })

    # ---------------------------------------------
    # Restrictions
    # ---------------------------------------------

    restrictions=[]

    for i,(name,_) in enumerate(CORRIDORS,start=14):

        if bits[i]:

            restrictions.append({

                "corridor":name,
                "type":"temporary_restriction"
            })

    # ---------------------------------------------
    # Benefit calculation
    # ---------------------------------------------

    active_corridors=sum(bits[:4])

    travel_saved=round(
        active_corridors*0.8
        +active_signals*0.25,
        2
    )

    queue_reduction=round(
        min(
            35,
            total_rerouted/EVENT["total_vehicles"]*100
        ),
        2
    )

    plan={

        "event":EVENT,

        "optimizer_used":optimizer,

        "bitstring":bitstring,

        "weather":WEATHER,

        "corridors":corridor_output,

        "signal_changes":signal_output,

        "restrictions":restrictions,

        "benefits":{

            "travel_time_saved_minutes":travel_saved,

            "queue_reduction_percent":queue_reduction
        }
    }

    return plan

# ---------------------------------------------------
# Save
# ---------------------------------------------------

if __name__=="__main__":

    plan=build_plan()

    with open(OUTPUT,"w") as f:
        json.dump(plan,f,indent=4)

    print("\nOptimization-Driven Traffic Plan")
    print("--------------------------------")

    print(f"Optimizer : {plan['optimizer_used']}")
    print(f"Bitstring : {plan['bitstring']}")

    print("\nEnabled Corridor Actions")

    for c in plan["corridors"]:

        if c["enabled"]:

            print(
                f"{c['corridor']:<22}"
                f"ON  "
                f"Overflow={c['overflow']:<4}"
                f"Rerouted={c['rerouted']}"
            )

    print("\nSignal Timing")

    for s in plan["signal_changes"]:

        print(
            f"{s['junction']}: "
            f"{s['old_green']}→{s['new_green']} "
            f"(+{s['extra_green']})"
        )

    print("\nEstimated Benefits")

    print(
        f"Travel Time Saved : "
        f"{plan['benefits']['travel_time_saved_minutes']} min"
    )

    print(
        f"Queue Reduction   : "
        f"{plan['benefits']['queue_reduction_percent']}%"
    )

    print("\nSaved")
    print(OUTPUT)