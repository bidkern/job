import csv
import math
import re
from pathlib import Path

ZIP_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "zip_centroids.csv"


def _load_zip_data() -> dict[str, tuple[float, float]]:
    records: dict[str, tuple[float, float]] = {}
    if not ZIP_DATA_PATH.exists():
        return records

    with ZIP_DATA_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return records

        aliases = {name.strip().lower(): name for name in reader.fieldnames}
        zip_key = aliases.get("zip")
        lat_key = aliases.get("lat") or aliases.get("latitude")
        lon_key = aliases.get("lon") or aliases.get("lng") or aliases.get("longitude")
        if not zip_key or not lat_key or not lon_key:
            return records

        for row in reader:
            zip_val = (row.get(zip_key) or "").strip()
            lat_val = (row.get(lat_key) or "").strip()
            lon_val = (row.get(lon_key) or "").strip()
            if not zip_val or not lat_val or not lon_val:
                continue
            try:
                records[zip_val] = (float(lat_val), float(lon_val))
            except ValueError:
                continue

    return records


def _load_zip_city_state() -> dict[str, tuple[str, str]]:
    records: dict[str, tuple[str, str]] = {}
    if not ZIP_DATA_PATH.exists():
        return records
    with ZIP_DATA_PATH.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            z = (row.get("zip") or "").strip()
            city = (row.get("city") or "").strip().lower()
            state = (row.get("state") or "").strip().lower()
            if z and city:
                records[z] = (city, state)
    return records


ZIP_COORDS = _load_zip_data()
ZIP_CITY_STATE = _load_zip_city_state()
CITY_STATE_TO_ZIP = {(city, state): z for z, (city, state) in ZIP_CITY_STATE.items()}
CITY_ONLY_TO_ZIP = {}
for z, (city, _state) in ZIP_CITY_STATE.items():
    CITY_ONLY_TO_ZIP.setdefault(city, z)


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_miles = 3958.8
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_miles * c


def infer_zip_from_location(location_text: str | None, city: str | None = None, state: str | None = None) -> str | None:
    if location_text:
        m = re.search(r"\b(\d{5})\b", location_text)
        if m:
            return m.group(1)

    city_norm = (city or "").strip().lower()
    state_norm = (state or "").strip().lower()

    if city_norm and state_norm:
        z = CITY_STATE_TO_ZIP.get((city_norm, state_norm))
        if z:
            return z

    text_norm = (location_text or "").lower()
    if text_norm:
        for c, z in CITY_ONLY_TO_ZIP.items():
            if c and c in text_norm:
                return z

    if city_norm:
        return CITY_ONLY_TO_ZIP.get(city_norm)

    return None


def distance_from_base_zip(base_zip: str, target_zip: str | None) -> float | None:
    if not target_zip:
        return None
    base = ZIP_COORDS.get(base_zip)
    target = ZIP_COORDS.get(target_zip)
    if not base or not target:
        return None
    return round(haversine_miles(base[0], base[1], target[0], target[1]), 2)
