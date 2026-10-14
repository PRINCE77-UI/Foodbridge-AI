from math import radians, sin, cos, asin, sqrt

HANDLING_MIN = 20
COOKED_MAX_MIN = 240
KG_PER_MEAL = 0.4

def safety_agent(hours: float, packaged: bool) -> dict:
    total = hours * 60
    win = (total if packaged else min(COOKED_MAX_MIN, total)) - HANDLING_MIN
    return {"ok": win >= 20, "window_min": int(win)}

def distance_km(a_lat, a_lon, b_lat, b_lon):
    if None in (a_lat, a_lon, b_lat, b_lon):
        return None
    la1, lo1, la2, lo2 = map(radians, (a_lat, a_lon, b_lat, b_lon))
    h = sin((la2 - la1) / 2) ** 2 + cos(la1) * cos(la2) * sin((lo2 - lo1) / 2) ** 2
    return round(2 * 6371 * asin(sqrt(h)), 1)

def match_tags(listing: dict, ngo: dict) -> list:
    tags = []
    if not (ngo.get("veg") and listing["non_veg"]):
        tags.append("Fits your diet rule")
    if not ngo.get("cap") or listing["meals"] <= ngo["cap"]:
        tags.append("Within your capacity")
    return tags

def can_accept(listing: dict, ngo: dict) -> bool:
    return not (ngo.get("veg") and listing["non_veg"])
