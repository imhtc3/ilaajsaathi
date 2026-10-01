"""Location layer: find the nearest hospitals and how long it takes to reach them.

Provider chain (first one that works wins):
  1. Google Maps Platform  (set GOOGLE_MAPS_API_KEY)
       - Geocoding API      : city / address -> lat,lng
       - Places API (New)   : Text Search for hospitals with a facility near the patient
       - Routes API         : Compute Route Matrix -> real driving time with traffic
  2. OpenStreetMap (free, no key): Nominatim geocoding + Overpass nearby hospitals
  3. Offline: curated government hospital list with coordinates + straight-line estimate

Directions links (google.com/maps/dir) work with no key at all.
Every call has a short timeout and never raises - the agent must keep working.
"""
from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

TIMEOUT = 8
UA = "IlaajSaathi/1.0 (hackathon prototype)"

CITY_CENTRES = {
    "delhi": (28.6139, 77.2090), "lucknow": (26.8467, 80.9462), "patna": (25.5941, 85.1376),
    "mumbai": (19.0760, 72.8777), "bengaluru": (12.9716, 77.5946), "jaipur": (26.9124, 75.7873),
}

# What to search for when an emergency needs a specific facility
FACILITY_QUERY = {
    "cath_lab": "hospital with 24 hour cath lab cardiac emergency",
    "stroke": "hospital emergency with CT scan stroke neurology",
    "neurosurgery": "hospital emergency neurosurgery MRI",
    "trauma": "trauma centre hospital emergency",
    "emergency": "hospital 24 hour emergency",
}
SPECIALTY_QUERY = {
    "cardiology": "government hospital cardiology",
    "orthopaedics": "government hospital orthopaedics",
    "urology": "government hospital urology",
    "ophthalmology": "government eye hospital",
    "neurology": "government hospital neurology",
    "neurosurgery": "government hospital neurosurgery",
    "pmr": "government hospital physiotherapy",
}


def google_key() -> str | None:
    return os.environ.get("GOOGLE_MAPS_API_KEY") or None


def maps_source() -> str:
    if google_key():
        return "google"
    return "openstreetmap" if os.environ.get("ILAAJ_USE_OSM", "1") == "1" else "offline"


def _get(url: str, headers: dict | None = None) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def _post(url: str, body: dict | str, headers: dict) -> dict | list:
    data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def directions_link(lat: float | None, lng: float | None, name: str = "", city: str = "") -> str:
    """Google Maps directions link - free, no API key, opens the Maps app on phones."""
    dest = f"{name}, {city}".strip(", ") if name else f"{lat},{lng}"
    return "https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=" + urllib.parse.quote(dest)


def haversine_km(a: tuple, b: tuple) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p = math.pi / 180
    h = math.sin((la2 - la1) * p / 2) ** 2 + math.cos(la1 * p) * math.cos(la2 * p) * math.sin((lo2 - lo1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def estimate_minutes(km: float) -> int:
    # road distance ~1.35x straight line, ~25 km/h average in Indian city traffic
    return max(3, round(km * 1.35 / 25 * 60))


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------
def geocode(text: str | None) -> dict | None:
    if not text:
        return None
    key = text.strip().lower()
    if google_key():
        try:
            q = urllib.parse.urlencode({"address": f"{text}, India", "key": google_key(), "region": "in"})
            d = _get(f"https://maps.googleapis.com/maps/api/geocode/json?{q}")
            if d.get("results"):
                loc = d["results"][0]["geometry"]["location"]
                return {"lat": loc["lat"], "lng": loc["lng"], "label": d["results"][0]["formatted_address"], "source": "google"}
        except Exception as e:
            print(f"[geo] google geocode failed: {e}")
    if maps_source() == "openstreetmap":
        try:
            q = urllib.parse.urlencode({"q": f"{text}, India", "format": "json", "limit": 1})
            d = _get(f"https://nominatim.openstreetmap.org/search?{q}")
            if d:
                return {"lat": float(d[0]["lat"]), "lng": float(d[0]["lon"]), "label": d[0]["display_name"], "source": "openstreetmap"}
        except Exception as e:
            print(f"[geo] nominatim failed: {e}")
    if key in CITY_CENTRES:
        lat, lng = CITY_CENTRES[key]
        return {"lat": lat, "lng": lng, "label": key.title(), "source": "offline"}
    return None


# ---------------------------------------------------------------------------
# Nearby hospital search
# ---------------------------------------------------------------------------
def google_places(query: str, lat: float, lng: float, radius_m: int = 15000, limit: int = 6) -> list[dict]:
    if not google_key():
        return []
    try:
        d = _post(
            "https://places.googleapis.com/v1/places:searchText",
            {"textQuery": query, "maxResultCount": limit, "languageCode": "en", "regionCode": "IN",
             "locationBias": {"circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}}},
            {"Content-Type": "application/json", "X-Goog-Api-Key": google_key(),
             "X-Goog-FieldMask": ("places.id,places.displayName,places.formattedAddress,places.location,"
                                  "places.nationalPhoneNumber,places.googleMapsUri,places.rating,"
                                  "places.currentOpeningHours.openNow,places.types")},
        )
        out = []
        for p in d.get("places", []):
            loc = p.get("location", {})
            out.append({
                "name": p.get("displayName", {}).get("text", "Hospital"),
                "address": p.get("formattedAddress", ""),
                "lat": loc.get("latitude"), "lng": loc.get("longitude"),
                "phone": p.get("nationalPhoneNumber"),
                "maps_url": p.get("googleMapsUri"),
                "rating": p.get("rating"),
                "open_now": (p.get("currentOpeningHours") or {}).get("openNow"),
                "source": "google",
            })
        return out
    except Exception as e:
        print(f"[geo] google places failed: {e}")
        return []


def osm_hospitals(lat: float, lng: float, radius_m: int = 8000, limit: int = 6) -> list[dict]:
    if maps_source() != "openstreetmap":
        return []
    try:
        q = (f'[out:json][timeout:8];(node["amenity"="hospital"](around:{radius_m},{lat},{lng});'
             f'way["amenity"="hospital"](around:{radius_m},{lat},{lng}););out center 30;')
        d = _post("https://overpass-api.de/api/interpreter", "data=" + urllib.parse.quote(q),
                  {"Content-Type": "application/x-www-form-urlencoded"})
        out = []
        for el in d.get("elements", []):
            tags = el.get("tags", {})
            if not tags.get("name"):
                continue
            c = el.get("center") or el
            out.append({"name": tags["name"], "address": tags.get("addr:full") or tags.get("addr:street", ""),
                        "lat": c.get("lat"), "lng": c.get("lon"), "phone": tags.get("phone"),
                        "operator_type": tags.get("operator:type"), "emergency": tags.get("emergency"),
                        "source": "openstreetmap"})
        out.sort(key=lambda h: haversine_km((lat, lng), (h["lat"], h["lng"])))
        return out[:limit]
    except Exception as e:
        print(f"[geo] overpass failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Travel time
# ---------------------------------------------------------------------------
def travel_times(origin: tuple, dests: list[tuple]) -> list[dict]:
    """Return [{minutes, km, source}] per destination."""
    if google_key() and dests:
        try:
            body = {
                "origins": [{"waypoint": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}}}],
                "destinations": [{"waypoint": {"location": {"latLng": {"latitude": a, "longitude": b}}}} for a, b in dests],
                "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE",
            }
            d = _post("https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix", body,
                      {"Content-Type": "application/json", "X-Goog-Api-Key": google_key(),
                       "X-Goog-FieldMask": "originIndex,destinationIndex,duration,distanceMeters,condition"})
            res = [None] * len(dests)
            for row in d:
                if row.get("condition") == "ROUTE_EXISTS":
                    secs = int(str(row.get("duration", "0s")).rstrip("s") or 0)
                    res[row["destinationIndex"]] = {"minutes": max(1, round(secs / 60)),
                                                    "km": round(row.get("distanceMeters", 0) / 1000, 1), "source": "google"}
            if all(res):
                return res
        except Exception as e:
            print(f"[geo] google routes failed: {e}")
    out = []
    for d in dests:
        km = haversine_km(origin, d)
        out.append({"minutes": estimate_minutes(km), "km": round(km * 1.35, 1), "source": "estimate"})
    return out
