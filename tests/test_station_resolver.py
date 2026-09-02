from __future__ import annotations

import json
from unittest.mock import patch

from server.core.plan_rules import resolve_station_id_from_plan
from server.core.station_resolver import (
    find_nearest_wsc_station,
    find_nearest_wsc_station_with_coverage,
    resolve_station_near_pour_point,
)


def test_resolve_station_id_auto_from_pour_point_wsc():
    cfg = {
        "streamflow_data_provider": "WSC",
        "pour_point_coords": "51.1781592/-115.5794334",
    }
    features = {
        "features": [
            {
                "geometry": {"coordinates": [-115.5717, 51.1722]},
                "properties": {
                    "STATION_NUMBER": "05BB001",
                    "STATION_NAME": "BOW RIVER AT BANFF",
                },
            }
        ]
    }

    def fake_fetch(url: str, timeout: float = 30.0):
        return features

    with patch("server.core.station_resolver._fetch_json", side_effect=fake_fetch):
        station_id = resolve_station_id_from_plan(cfg, "")
        assert station_id == "05BB001"


def test_resolve_station_near_pour_point_returns_note():
    features = {
        "features": [
            {
                "geometry": {"coordinates": [-115.5717, 51.1722]},
                "properties": {
                    "STATION_NUMBER": "05BB001",
                    "STATION_NAME": "BOW RIVER AT BANFF",
                },
            }
        ]
    }

    with patch("server.core.station_resolver._fetch_json", return_value=features):
        hit = resolve_station_near_pour_point("WSC", "51.1781592/-115.5794334")
        assert hit is not None
        assert hit[0] == "05BB001"
        assert "Auto-selected nearest WSC gauge" in hit[1]


def test_find_nearest_wsc_station_picks_closest():
    features = {
        "features": [
            {
                "geometry": {"coordinates": [-115.60, 51.18]},
                "properties": {"STATION_NUMBER": "05BB999", "STATION_NAME": "FAR"},
            },
            {
                "geometry": {"coordinates": [-115.5717, 51.1722]},
                "properties": {"STATION_NUMBER": "05BB001", "STATION_NAME": "NEAR"},
            },
        ]
    }
    with patch("server.core.station_resolver._fetch_json", return_value=features):
        hit = find_nearest_wsc_station(51.1781592, -115.5794334)
        assert hit is not None
        assert hit[0] == "05BB001"


def test_find_nearest_wsc_station_with_coverage_skips_stale_nearest():
    from datetime import datetime

    features = {
        "features": [
            {
                "geometry": {"coordinates": [-115.58, 51.178]},
                "properties": {"STATION_NUMBER": "05BA006", "STATION_NAME": "JOHNSTON CREEK"},
            },
            {
                "geometry": {"coordinates": [-115.5717, 51.1722]},
                "properties": {"STATION_NUMBER": "05BB001", "STATION_NAME": "BOW RIVER AT BANFF"},
            },
        ]
    }

    def fake_fetch(url: str, timeout: float = 30.0):
        if "hydrometric-daily-mean" in url:
            if "STATION_NUMBER=05BA006" in url or "05BA006" in url:
                return {"numberMatched": 0, "features": []}
            if "STATION_NUMBER=05BB001" in url or "05BB001" in url:
                return {"numberMatched": 56, "features": [{}]}
        return features

    start = datetime(2022, 4, 1)
    end = datetime(2022, 5, 26)
    with patch("server.core.station_resolver._fetch_json", side_effect=fake_fetch):
        hit = find_nearest_wsc_station_with_coverage(51.1781592, -115.5794334, start, end)
        assert hit is not None
        assert hit[0] == "05BB001"


def test_resolve_station_id_uses_coverage_when_experiment_dates_present():
    cfg = {
        "streamflow_data_provider": "WSC",
        "pour_point_coords": "51.1781592/-115.5794334",
        "experiment_time_start": "2022-04-01 01:00",
        "experiment_time_end": "2022-05-26 01:00",
    }

    with patch(
        "server.core.station_resolver.find_nearest_wsc_station_with_coverage",
        return_value=("05BB001", "BOW RIVER AT BANFF", 900.0),
    ) as coverage_lookup:
        station_id = resolve_station_id_from_plan(cfg, "")
        assert station_id == "05BB001"
        coverage_lookup.assert_called_once()


def test_resolve_station_near_pour_point_coverage_note():
    from datetime import datetime

    features = {
        "features": [
            {
                "geometry": {"coordinates": [-115.5717, 51.1722]},
                "properties": {"STATION_NUMBER": "05BB001", "STATION_NAME": "BOW RIVER AT BANFF"},
            }
        ]
    }

    def fake_fetch(url: str, timeout: float = 30.0):
        if "hydrometric-daily-mean" in url:
            return {"numberMatched": 10, "features": [{}]}
        return features

    with patch("server.core.station_resolver._fetch_json", side_effect=fake_fetch):
        hit = resolve_station_near_pour_point(
            "WSC",
            "51.1781592/-115.5794334",
            experiment_start="2022-04-01 01:00",
            experiment_end="2022-05-26 01:00",
        )
        assert hit is not None
        assert hit[0] == "05BB001"
        assert "with data covering" in hit[1]
