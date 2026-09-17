"""Resolve streamflow gauge station IDs from pour-point coordinates."""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from server.core.local_domain import _parse_lat_lon_pair


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _fetch_json(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
        return json.loads(resp.read().decode("utf-8"))


def _parse_experiment_datetime(value: str | None) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _list_wsc_stations_near(
    lat: float,
    lon: float,
    *,
    search_pad_deg: float = 0.35,
    limit: int = 100,
) -> list[tuple[str, str, float]]:
    """Return WSC gauges near (lat, lon) sorted by distance (m)."""
    bbox = f"{lon - search_pad_deg},{lat - search_pad_deg},{lon + search_pad_deg},{lat + search_pad_deg}"
    params = urllib.parse.urlencode({"f": "json", "limit": str(limit), "bbox": bbox})
    url = f"https://api.weather.gc.ca/collections/hydrometric-stations/items?{params}"
    try:
        data = _fetch_json(url)
    except Exception:
        return []

    hits: list[tuple[str, str, float]] = []
    for feat in data.get("features") or []:
        props = feat.get("properties") or {}
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        if len(coords) < 2 or coords[0] is None or coords[1] is None:
            continue
        slon, slat = float(coords[0]), float(coords[1])
        station_id = str(props.get("STATION_NUMBER") or "").strip()
        if not station_id:
            continue
        name = str(props.get("STATION_NAME") or station_id)
        dist_m = _haversine_m(lat, lon, slat, slon)
        hits.append((station_id, name, dist_m))
    hits.sort(key=lambda item: item[2])
    return hits


def wsc_station_covers_period(
    station_id: str,
    experiment_start: datetime,
    experiment_end: datetime,
) -> bool:
    """True when GeoMet has at least one daily mean record in the experiment window."""
    start_d = experiment_start.date().isoformat()
    end_d = experiment_end.date().isoformat()
    params = urllib.parse.urlencode(
        {
            "f": "json",
            "limit": "1",
            "STATION_NUMBER": station_id,
            "datetime": f"{start_d}T00:00:00Z/{end_d}T23:59:59Z",
        }
    )
    url = f"https://api.weather.gc.ca/collections/hydrometric-daily-mean/items?{params}"
    try:
        data = _fetch_json(url)
    except Exception:
        return False
    matched = data.get("numberMatched")
    if isinstance(matched, int):
        return matched > 0
    return bool(data.get("features"))


def find_nearest_wsc_station(
    lat: float,
    lon: float,
    *,
    search_pad_deg: float = 0.35,
    limit: int = 100,
) -> tuple[str, str, float] | None:
    """Return (station_id, station_name, distance_m) for nearest active WSC gauge."""
    hits = _list_wsc_stations_near(lat, lon, search_pad_deg=search_pad_deg, limit=limit)
    return hits[0] if hits else None


def find_nearest_wsc_station_with_coverage(
    lat: float,
    lon: float,
    experiment_start: datetime,
    experiment_end: datetime,
    *,
    search_pad_deg: float = 0.35,
    limit: int = 100,
    max_candidates: int = 15,
) -> tuple[str, str, float] | None:
    """Return nearest WSC gauge that has streamflow data in the experiment window."""
    for station_id, name, dist_m in _list_wsc_stations_near(
        lat, lon, search_pad_deg=search_pad_deg, limit=limit
    )[:max_candidates]:
        if wsc_station_covers_period(station_id, experiment_start, experiment_end):
            return station_id, name, dist_m
    return None


def _list_usgs_stations_near(
    lat: float,
    lon: float,
    *,
    search_pad_deg: float = 0.35,
) -> list[tuple[str, str, float]]:
    """Return USGS stream gauges near (lat, lon) sorted by distance (m)."""
    bbox = f"{lon - search_pad_deg},{lat - search_pad_deg},{lon + search_pad_deg},{lat + search_pad_deg}"
    params = urllib.parse.urlencode(
        {
            "format": "json",
            "bBox": bbox,
            "siteType": "ST",
            "siteStatus": "active",
            "hasDataTypeCd": "dv",
            "parameterCd": "00060",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/site/?{params}"
    try:
        data = _fetch_json(url, timeout=60.0)
    except Exception:
        return []

    hits: list[tuple[str, str, float]] = []
    for site in (data.get("value") or {}).get("timeSeries") or []:
        source = site.get("sourceInfo") or {}
        geo = source.get("geoLocation") or {}
        geog = geo.get("geogLocation") or {}
        try:
            slat = float(geog.get("latitude"))
            slon = float(geog.get("longitude"))
        except (TypeError, ValueError):
            continue
        station_id = str(source.get("siteCode", [{}])[0].get("value") or "").strip()
        if not station_id:
            continue
        name = str(source.get("siteName") or station_id)
        dist_m = _haversine_m(lat, lon, slat, slon)
        hits.append((station_id, name, dist_m))
    hits.sort(key=lambda item: item[2])
    return hits


def usgs_station_covers_period(
    station_id: str,
    experiment_start: datetime,
    experiment_end: datetime,
) -> bool:
    """True when USGS daily discharge exists in the experiment window."""
    params = urllib.parse.urlencode(
        {
            "format": "json",
            "sites": station_id,
            "startDT": experiment_start.strftime("%Y-%m-%d"),
            "endDT": experiment_end.strftime("%Y-%m-%d"),
            "parameterCd": "00060",
        }
    )
    url = f"https://waterservices.usgs.gov/nwis/dv/?{params}"
    try:
        data = _fetch_json(url, timeout=60.0)
    except Exception:
        return False
    for site in (data.get("value") or {}).get("timeSeries") or []:
        values = ((site.get("values") or [{}])[0].get("value") or [])
        if values:
            return True
    return False


def find_nearest_usgs_station(
    lat: float,
    lon: float,
    *,
    search_pad_deg: float = 0.35,
) -> tuple[str, str, float] | None:
    """Return (station_id, station_name, distance_m) for nearest active USGS stream gauge."""
    hits = _list_usgs_stations_near(lat, lon, search_pad_deg=search_pad_deg)
    return hits[0] if hits else None


def find_nearest_usgs_station_with_coverage(
    lat: float,
    lon: float,
    experiment_start: datetime,
    experiment_end: datetime,
    *,
    search_pad_deg: float = 0.35,
    max_candidates: int = 15,
) -> tuple[str, str, float] | None:
    """Return nearest USGS gauge that has streamflow data in the experiment window."""
    for station_id, name, dist_m in _list_usgs_stations_near(lat, lon, search_pad_deg=search_pad_deg)[
        :max_candidates
    ]:
        if usgs_station_covers_period(station_id, experiment_start, experiment_end):
            return station_id, name, dist_m
    return None


def resolve_station_near_pour_point(
    provider: str,
    pour_point_coords: str,
    *,
    experiment_start: str | None = None,
    experiment_end: str | None = None,
) -> tuple[str, str] | None:
    """
    Pick a public gauge near the pour point for WSC or USGS.

    When experiment dates are provided, prefer the nearest gauge with obs in that window.

    Returns (station_id, note) or None when lookup fails.
    """
    parsed = _parse_lat_lon_pair(pour_point_coords)
    if parsed is None:
        return None
    lat, lon = parsed
    provider_u = (provider or "WSC").strip().upper()
    exp_start = _parse_experiment_datetime(experiment_start)
    exp_end = _parse_experiment_datetime(experiment_end)
    use_coverage = exp_start is not None and exp_end is not None

    if provider_u == "WSC":
        if use_coverage:
            hit = find_nearest_wsc_station_with_coverage(lat, lon, exp_start, exp_end)
        else:
            hit = find_nearest_wsc_station(lat, lon)
    elif provider_u == "USGS":
        if use_coverage:
            hit = find_nearest_usgs_station_with_coverage(lat, lon, exp_start, exp_end)
        else:
            hit = find_nearest_usgs_station(lat, lon)
    else:
        return None

    if hit is None:
        return None
    station_id, name, dist_m = hit
    if use_coverage:
        note = (
            f"Auto-selected nearest {provider_u} gauge {station_id} ({name}) with data "
            f"covering {exp_start.date()} to {exp_end.date()}, "
            f"~{dist_m / 1000:.1f} km from pour point {lat:.5f}/{lon:.5f}."
        )
    else:
        note = (
            f"Auto-selected nearest {provider_u} gauge {station_id} ({name}) "
            f"~{dist_m / 1000:.1f} km from pour point {lat:.5f}/{lon:.5f}."
        )
    return station_id, note
