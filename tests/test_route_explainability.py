from python.route_explainability import explain_plan
from python.integration.id_mapper import CORRIDOR_MAP


def _plan(optimizer="Quantum", bitstring="100000000000000000"):
    return {
        "optimizer_used": optimizer, "status": "completed", "run_id": "run-1",
        "bitstring": bitstring,
        "corridors": [{"corridor": name, "enabled": index == 0, "rerouted": 2,
                       "remaining_queue": 4} for index, name in enumerate(CORRIDOR_MAP)],
        "signal_changes": [], "restrictions": [], "applied_to_sumo": False,
    }


def _variables():
    variables = [{"id": f"x{i + 1}", "category": "route_diversion", "target": name,
                  "description": f"route {name}"} for i, name in enumerate(CORRIDOR_MAP)]
    variables.extend({"id": f"x{i + 5}", "category": "signal_extension", "target": f"J{i + 1}",
                      "description": "signal"} for i in range(10))
    variables.extend({"id": f"x{i + 15}", "category": "temporary_restriction", "target": name,
                      "description": "restriction"} for i, name in enumerate(CORRIDOR_MAP))
    return variables


def test_explainability_covers_registry_corridors_and_uses_actual_actions():
    result = explain_plan(_plan(), {}, {}, _variables(), {"Anna Salai": {"valid": True, "errors": []}})
    assert [item["corridor"] for item in result["corridors"]] == list(CORRIDOR_MAP)
    assert result["corridors"][0]["status"] == "APPLICABLE"
    assert "2 vehicles" in result["corridors"][0]["recommendation"]
    assert all(item["status"] == "NO_ACTION" for item in result["corridors"][1:])
    assert result["applied_to_sumo"] is False


def test_constraint_rejection_withholds_recommendation():
    result = explain_plan(_plan(), {}, {}, _variables(), {"Anna Salai": {"valid": False, "errors": []}})
    assert result["corridors"][0]["status"] == "CONSTRAINED"
    assert "recommendation withheld" in result["corridors"][0]["recommendation"]


def test_bitstring_decode_mismatch_never_emits_route_recommendation():
    plan = _plan(bitstring="000000000000000000")
    result = explain_plan(plan, {}, {}, _variables())
    assert result["corridors"][0]["status"] == "REVIEW_REQUIRED"
    assert "no route recommendation" in result["corridors"][0]["recommendation"]


def test_classical_fallback_source_is_preserved():
    result = explain_plan(_plan("Classical (Fallback)"), {}, {}, _variables())
    assert result["source"] == "Classical (Fallback)"
    assert all(item["source"] == "Classical (Fallback)" for item in result["corridors"])
