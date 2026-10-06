"""Pure helpers for measured paired-simulation comparisons."""


def measured_delta(classical, quantum, synchronized=True):
    if not synchronized or not isinstance(classical, (int, float)) or not isinstance(quantum, (int, float)):
        return None
    return round(float(quantum) - float(classical), 2)


def measured_improvement_percent(classical, quantum, *, higher_is_better=False, synchronized=True):
    if (not synchronized or not isinstance(classical, (int, float))
            or not isinstance(quantum, (int, float)) or classical == 0):
        return None
    change = ((quantum - classical) if higher_is_better else (classical - quantum)) / abs(classical) * 100.0
    return round(change, 2)


def compare_measurements(classical, quantum, synchronized=True):
    """Compare real metric maps; missing/zero-baseline percentages remain None."""
    output = {}
    for key in set(classical) | set(quantum):
        c_value, q_value = classical.get(key), quantum.get(key)
        higher = key in {"avg_speed_kmh", "throughput_vehicles_per_hour"}
        output[key] = {
            "quantum_minus_classical": measured_delta(c_value, q_value, synchronized),
            "improvement_percent": measured_improvement_percent(
                c_value, q_value, higher_is_better=higher, synchronized=synchronized),
        }
    return output
