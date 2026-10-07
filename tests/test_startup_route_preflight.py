from unittest.mock import MagicMock, patch

import pytest

from python.scenario_inputs import (
    RouteValidationError,
    default_density,
    make_route_variant,
    validate_route,
    validate_route_file,
    validate_scenario_routes,
)
from python.startup_checks import StartupCheckError, ensure_server_port_available


def test_disconnected_stadium_ring_edges_are_rejected():
    report = validate_route(["E_STAD_RING_SW", "E_STAD_RING_WS"], vehicle_class="taxi")

    assert report["valid"] is False
    assert report["errors"][0]["code"] == "NO_SUMO_CONNECTION"
    assert report["errors"][0]["from_edge"] == "E_STAD_RING_SW"
    assert report["errors"][0]["to_edge"] == "E_STAD_RING_WS"
    failure = RouteValidationError(report)
    assert failure.code == "ROUTE_INVALID"


def test_normal_day_stadium_taxi_route_is_connected_and_accessible():
    report = validate_route_file("sumo/normal_day.rou.xml")

    assert report["valid"] is True, report["errors"]
    scenario = validate_scenario_routes("normal_day")
    assert scenario["valid"] is True


@pytest.mark.parametrize("scenario", ["normal_day", "event_day"])
def test_stadium_demand_route_variants_validate_before_sumo_start(scenario):
    generated = make_route_variant(scenario, default_density(scenario))
    try:
        report = validate_route_file(generated)
        assert report["valid"] is True, report["errors"]
    finally:
        generated.unlink(missing_ok=True)


def test_startup_reuses_existing_project_server_without_terminating_it():
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    sock.bind.side_effect = OSError("address in use")
    owner = {"pid": 4321, "name": "python.exe", "address": "127.0.0.1:8000"}

    with patch("python.startup_checks.socket.socket", return_value=sock), \
            patch("python.startup_checks._project_server_is_running", return_value=True), \
            patch("python.startup_checks._port_owners", return_value=[owner]):
        is_available = ensure_server_port_available("127.0.0.1", 8000)

    assert is_available is False
    sock.bind.assert_called_once_with(("127.0.0.1", 8000))


def test_startup_reports_unrelated_port_owner_without_terminating_it():
    sock = MagicMock()
    sock.__enter__.return_value = sock
    sock.__exit__.return_value = False
    sock.bind.side_effect = OSError("address in use")
    owner = {"pid": 4321, "name": "other-app.exe", "address": "127.0.0.1:8000"}

    with patch("python.startup_checks.socket.socket", return_value=sock), \
            patch("python.startup_checks._project_server_is_running", return_value=False), \
            patch("python.startup_checks._port_owners", return_value=[owner]):
        with pytest.raises(StartupCheckError) as caught:
            ensure_server_port_available("127.0.0.1", 8000)

    assert caught.value.code == "SERVER_PORT_IN_USE"
    assert caught.value.details["owners"] == [owner]
    assert "PID 4321" in str(caught.value)
