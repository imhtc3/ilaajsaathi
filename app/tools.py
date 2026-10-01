"""IlaajSaathi tools.

Every tool is a plain Python function: input -> output dict.
The orchestrator (agent.py) decides which tools to call and in what order.
Hospital search and travel times come from geo.py (Google Maps / OpenStreetMap / offline data).
"""
from __future__ import annotations

import csv
import os
import re
import uuid
from datetime import datetime, timedelta

from . import geo

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
OUT_DIR = os.environ.get("ILAAJ_OUT_DIR", os.path.join(os.path.dirname(__file__), "generated"))
os.makedirs(OUT_DIR, exist_ok=True)


def _load(name: str) -> list[dict]:
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
        return list(csv.DictReader(f))


HOSPITALS = _load("hospitals.csv")
PROCEDURES = _load("procedures.csv")
GENERICS = _load("generics.csv")

SPECIALTY_FOR = {
    "heart": ["cardiology"], "knee": ["orthopaedics"], "kidney": ["urology"], "eye": ["ophthalmology"],
    "back": ["orthopaedics", "neurosurgery"], "neck": ["orthopaedics", "neurosurgery"],
    "shoulder": ["orthopaedics"], "hand": ["orthopaedics", "neurology"], "leg": ["orthopaedics"],
}
DEPT_LABEL = {"cardiology": "heart (cardiology)", "orthopaedics": "bones & joints (ortho)", "urology": "kidney (urology)",
              "ophthalmology": "eye", "neurosurgery": "brain & spine surgery", "neurology": "nerves (neuro)",
              "pmr": "physiotherapy & rehab"}
FACILITY_LABEL = {"cath_lab": "24x7 cath lab for heart attacks", "stroke": "CT scan and stroke care",
                  "neurosurgery": "emergency spine & brain surgery", "trauma": "trauma centre",
                  "emergency": "24x7 emergency", "dialysis": "dialysis"}

# ---------------------------------------------------------------------------
# 1. Safety gate. Rule-based on purpose, never left to the LLM.
#    Each urgent flag names the FACILITY the patient needs, so we can route them.
# ---------------------------------------------------------------------------
def _any(t: str, pats: list[str]) -> bool:
    return any(re.search(p, t) for p in pats)


CHEST = [r"chest pain", r"chest (is )?(tight|heavy|pressure)", r"seene (me|mein) dard", r"seene me", r"सीने", r"छाती"]
CARDIAC_DANGER = [r"sweat", r"pasina", r"पसीना", r"breath", r"saans", r"सांस", r"left arm", r"\barm\b", r"jaw", r"jabd",
                  r"sudden", r"right now", r"\babhi\b", r"severe", r"tez dard", r"at rest", r"अचानक", r"अभी", r"तेज़"]
URGENT_RULES = [
    ("heart_attack", "Possible heart attack (chest pain with sweating, breathlessness or arm/jaw pain)", "cath_lab"),
    ("stroke", "Possible stroke (face drooping, slurred speech or one-sided weakness)", "stroke"),
    ("spinal", "Loss of bladder/bowel control or worsening leg weakness", "neurosurgery"),
    ("trauma", "Serious injury (accident, head injury or heavy bleeding)", "trauma"),
    ("breathing", "Severe breathlessness", "emergency"),
    ("unconscious", "Fainting or unconsciousness", "emergency"),
]
STROKE = [r"face (is )?(droop|drooping|tilted|crooked)", r"slurred", r"can'?t speak", r"cannot speak", r"bol nahi pa",
          r"one side (of (the|my) body )?(weak|numb)", r"(left|right) side (weak|numb)", r"paraly", r"lakwa", r"लकवा",
          r"मुंह टेढ़ा", r"\bstroke\b", r"brain attack"]
SPINAL = [r"(control|hold).{0,12}(urine|pee|stool|toilet)", r"(urine|pee).{0,15}(leak|control)", r"bladder", r"bowel",
          r"peshab.{0,15}(control|ruk|nahi)", r"पेशाब", r"(groin|saddle).{0,10}numb", r"foot drop",
          r"(legs?|arms?) (feel|feels|are|is|getting|became) (very )?weak", r"can'?t (walk|stand)", r"चल नहीं पा"]
TRAUMA = [r"accident", r"head injury", r"heavy bleeding", r"bleeding (a lot|heavily)", r"fell from", r"हादसा",
          r"दुर्घटना", r"sir (pe|par) chot", r"सिर पर चोट"]
BREATHING = [r"can'?t breathe", r"cannot breathe", r"saans nahi", r"सांस नहीं", r"gasping", r"breathless at rest"]
UNCONSCIOUS = [r"unconscious", r"fainted", r"faint(ing)?\b", r"behosh", r"बेहोश"]
SOON_RULES = [
    ("chest_exertion", "Chest pain on walking or climbing stairs - see a heart doctor within days", None),
    ("fever_spine", "Fever along with back or neck pain", None),
    ("weight_loss_cancer", "Unexplained weight loss or cancer history", None),
    ("blood_urine", "Blood in urine", None),
    ("fall", "Pain started after a fall", None),
]


def red_flag_check(text: str) -> dict:
    t = text.lower()
    found = []
    chest = _any(t, CHEST)
    if re.search(r"heart attack|दिल का दौरा|हार्ट अटैक", t) or (chest and _any(t, CARDIAC_DANGER)):
        found.append(URGENT_RULES[0])
    elif chest:
        found.append(SOON_RULES[0])
    for rule, pats in [(URGENT_RULES[1], STROKE), (URGENT_RULES[2], SPINAL), (URGENT_RULES[3], TRAUMA),
                       (URGENT_RULES[4], BREATHING), (URGENT_RULES[5], UNCONSCIOUS)]:
        if _any(t, pats):
            found.append(rule)
    if _any(t, [r"fever", r"bukhar", r"बुखार"]) and _any(t, [r"back", r"neck", r"spine", r"kamar", r"कमर"]):
        found.append(SOON_RULES[1])
    if _any(t, [r"weight loss", r"losing weight", r"cancer", r"वजन कम"]):
        found.append(SOON_RULES[2])
    if _any(t, [r"blood in (my )?urine", r"peshab me khoon", r"पेशाब में खून"]):
        found.append(SOON_RULES[3])
    if _any(t, [r"\bfell\b", r"\bfall\b", r"gir gay", r"गिर"]) and not _any(t, TRAUMA):
        found.append(SOON_RULES[4])

    flags = [{"key": k, "label": lbl, "facility": fac, "urgent": fac is not None} for k, lbl, fac in found]
    urgent = [f for f in flags if f["urgent"]]
    priority = ["cath_lab", "stroke", "trauma", "neurosurgery", "emergency"]
    facility = min((f["facility"] for f in urgent), key=priority.index) if urgent else None
    return {
        "red_flags": flags, "urgent": bool(urgent), "facility_needed": facility,
        "facility_label": FACILITY_LABEL.get(facility),
        "advice": ("Go to the nearest hospital with the right facility now, or call 108 for a free ambulance."
                   if urgent else ("If it gets worse or comes on at rest, go to emergency or call 108."
                                   if flags else "No emergency warning signs found in what you shared.")),
    }


# ---------------------------------------------------------------------------
# Location helpers shared by hospital tools
# ---------------------------------------------------------------------------
def _origin(profile: dict) -> dict | None:
    if profile.get("lat") is not None and profile.get("lng") is not None:
        return {"lat": float(profile["lat"]), "lng": float(profile["lng"]), "label": "your location", "source": "device"}
    return geo.geocode(profile.get("city"))


def _norm(name: str) -> set:
    stop = {"hospital", "the", "of", "and", "institute", "medical", "sciences", "dr", "govt", "government", "&"}
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in stop and len(w) > 2}


def _merge(curated: list[dict], extra: list[dict]) -> list[dict]:
    out = list(curated)
    for e in extra:
        if e.get("lat") is None:
            continue
        dup = any(len(_norm(e["name"]) & _norm(c["name"])) >= 2 or
                  (c.get("lat") is not None and geo.haversine_km((e["lat"], e["lng"]), (c["lat"], c["lng"])) < 0.3)
                  for c in out)
        if not dup:
            out.append(e)
    return out


def _curated_rows(origin: dict | None, city: str | None, max_km: float = 60) -> list[dict]:
    rows = []
    for h in HOSPITALS:
        lat, lng = float(h["lat"]), float(h["lng"])
        near = origin and geo.haversine_km((origin["lat"], origin["lng"]), (lat, lng)) <= max_km
        if near or (not origin and city and h["city"] == city.lower()):
            rows.append({"name": h["name"], "address": f'{h["area"]}, {h["city"].title()}', "city": h["city"],
                         "lat": lat, "lng": lng, "type": h["type"], "fee": h["fee_note"],
                         "departments": h["departments"].split(";"), "facilities": h["facilities"].split(";"),
                         "source": "curated"})
    return rows


def _with_travel(origin: dict | None, rows: list[dict]) -> list[dict]:
    if origin and rows:
        times = geo.travel_times((origin["lat"], origin["lng"]), [(r["lat"], r["lng"]) for r in rows])
        for r, t in zip(rows, times):
            r.update({"minutes": t["minutes"], "km": t["km"], "time_source": t["source"]})
    for r in rows:
        r["directions"] = r.get("maps_url") or (geo.directions_link(r["lat"], r["lng"], r["name"], r.get("city", ""))
                                               if r["source"] == "curated" else geo.directions_link(r["lat"], r["lng"]))
    return rows


# ---------------------------------------------------------------------------
# 2. Emergency routing: nearest hospital WITH the facility the symptoms need
# ---------------------------------------------------------------------------
def route_emergency(profile: dict, facility: str) -> dict:
    origin = _origin(profile)
    base = {"facility": facility, "facility_label": FACILITY_LABEL.get(facility, "emergency care"),
            "call": "108", "call_note": "Free ambulance in most states",
            "rights": "Hospitals must give emergency first aid and stabilisation. Don't let payment questions delay treatment; "
                      "Ayushman Bharat cards are accepted for emergencies at empanelled hospitals.",
            "maps": geo.maps_source()}
    if not origin:
        return {**base, "needs_location": True, "hospitals": [],
                "note": "Share your location or type your city to get the nearest matching hospital. Call 108 now."}
    curated = [r for r in _curated_rows(origin, profile.get("city")) if facility in r["facilities"]]
    found = geo.google_places(geo.FACILITY_QUERY.get(facility, geo.FACILITY_QUERY["emergency"]),
                              origin["lat"], origin["lng"], radius_m=12000)
    for f in found:
        f["facilities"] = [facility]
        f["type"] = "Check: government or private"
        f["verify"] = "Call ahead to confirm the facility is available right now"
    if not geo.google_key():
        # Free OpenStreetMap search. Facilities are rarely tagged there, so prefer large hospitals
        # (medical colleges, district/civil hospitals, institutes) and ones tagged emergency=yes.
        osm = geo.osm_hospitals(origin["lat"], origin["lng"], radius_m=15000, limit=20)
        osm = [dict(h, facilities=["emergency"], tier=1 if h["big"] else 2,
                    verify="Facility not confirmed on the map - call ahead, or let 108 choose the hospital")
               for h in osm if h["big"] or h["emergency"]] or \
              [dict(h, facilities=["emergency"], tier=2, verify="Facility not confirmed - call ahead or use 108")
               for h in osm[:4]]
        found = found + osm
    for r in curated:
        r["confirmed"], r["tier"] = True, 0
    for f in found:
        f.setdefault("tier", 0)  # Google results matched the facility search
        f["confirmed"] = False
    rows = _with_travel(origin, _merge(curated, found))
    # Known facility (our list or a Google facility search) first, then large hospitals, then by travel time
    rows.sort(key=lambda r: (r.get("tier", 2), r.get("minutes", 999)))
    govt = next((r for r in rows if r.get("type") == "Government"), None)
    return {**base, "needs_location": False, "origin": origin.get("label"), "hospitals": rows[:4],
            "best": rows[0] if rows else None, "nearest_government": govt}


# ---------------------------------------------------------------------------
# 3. Ayushman Bharat PM-JAY eligibility (simplified, demo logic)
# ---------------------------------------------------------------------------
def check_pmjay_eligibility(profile: dict) -> dict:
    age = profile.get("age")
    card = (profile.get("ration_card") or "").lower()
    income = profile.get("monthly_income")
    reasons, likely = [], "unknown"
    if isinstance(age, int) and age >= 70:
        likely = "likely"
        reasons.append("All citizens aged 70+ can get the Ayushman Vay Vandana card, whatever their income.")
    if card in {"aay", "antyodaya", "bpl", "priority", "phh", "nfsa"}:
        likely = "likely"
        reasons.append("Families with an AAY/BPL/priority ration card are often covered (rules vary by state).")
    if likely == "unknown" and isinstance(income, int) and income <= 15000:
        likely = "possible"
        reasons.append("Low household income - you may be in the beneficiary list; check with your Aadhaar.")
    if not reasons:
        reasons.append("Not enough information. Checking takes 2 minutes with Aadhaar or ration card.")
    return {
        "status": likely,
        "cover": "Up to Rs 5 lakh per family per year, cashless, at empanelled hospitals",
        "reasons": reasons,
        "how_to_check": "beneficiary.nha.gov.in or call 14555, or visit any CSC / empanelled hospital Ayushman desk",
        "disclaimer": "Eligibility here is an estimate. Only the official check is final.",
    }


# ---------------------------------------------------------------------------
# 4. Free / minimal-cost consultation options
# ---------------------------------------------------------------------------
def teleconsult_options(profile: dict) -> dict:
    return {"options": [
        {"name": "eSanjeevani (Govt of India)", "cost": "Free",
         "how": "esanjeevani.mohfw.gov.in or the eSanjeevani app - video consult with a government doctor",
         "best_for": "First opinion, reviewing reports, deciding next step"},
        {"name": "Government hospital OPD", "cost": "Free or minimal registration fee",
         "how": "Book online at ors.gov.in for central hospitals, or walk in early morning",
         "best_for": "Specialist exam, tests at subsidised rates"},
        {"name": "Ayushman Arogya Mandir (health & wellness centre)", "cost": "Free",
         "how": "Your nearest PHC / wellness centre",
         "best_for": "Basic care, referral letter, free medicines"},
    ]}


# ---------------------------------------------------------------------------
# 5. Affordable hospital finder (government first, nearest first)
# ---------------------------------------------------------------------------
def find_hospitals(profile: dict, conditions: list[str], limit: int = 4) -> dict:
    wanted = set()
    for c in conditions or []:
        wanted.update(SPECIALTY_FOR.get(c, []))
    wanted = wanted or {"orthopaedics", "cardiology"}
    origin = _origin(profile)
    if not origin and not profile.get("city"):
        return {"hospitals": [], "note": "Share your location or city to see the nearest government hospitals.",
                "maps": geo.maps_source()}
    rows = [r for r in _curated_rows(origin, profile.get("city"), max_km=40) if wanted & set(r["departments"])]
    if origin and geo.google_key():
        spec = sorted(wanted)[0]
        found = geo.google_places(geo.SPECIALTY_QUERY.get(spec, "government hospital"), origin["lat"], origin["lng"])
        for f in found:
            f["type"] = "Check: government or private"
        rows = _merge(rows, found)
    elif origin:
        # Free OpenStreetMap search: keep government hospitals (by operator tag or name), specialty-tagged first.
        osm = [h for h in geo.osm_hospitals(origin["lat"], origin["lng"], radius_m=20000, limit=30) if h["type"] == "Government"]
        for h in osm:
            h["fee"] = "Government hospital - ask for OPD timings and Ayushman desk"
        osm.sort(key=lambda h: (not (wanted & set(h["departments"])), not h["big"]))
        rows = _merge(rows, osm[:6])
    rows = _with_travel(origin, rows)
    for r in rows:
        if r.get("departments"):
            r["departments"] = [DEPT_LABEL.get(d, d) for d in r["departments"] if d in wanted] or r["departments"]
    rows.sort(key=lambda r: (r.get("type") != "Government", r.get("minutes", 999)))
    covered = sorted({h["city"].title() for h in HOSPITALS})
    note = "Ask at the Ayushman desk whether your treatment is covered there."
    if not rows:
        note = (f"No government hospital found nearby on the map. Try your district headquarters, or use eSanjeevani. "
                f"Curated data covers {', '.join(covered)}.")
    return {"origin": (origin or {}).get("label") or (profile.get("city") or "").title(), "hospitals": rows[:limit],
            "note": note, "maps": geo.maps_source()}


# ---------------------------------------------------------------------------
# 6. Cost comparison: government vs private
# ---------------------------------------------------------------------------
def _fmt(n: int) -> str:
    if n >= 100000:
        return f"Rs {n/100000:.1f} lakh".replace(".0 lakh", " lakh")
    return f"Rs {n:,}"


def estimate_costs(conditions: list[str], surgery_advised: bool, budget: int | None, text: str = "") -> dict:
    conds = list(conditions or [])
    t = (text or "").lower()
    items = []
    for p in PROCEDURES:
        applies = set(p["applies_to"].split(";"))
        if not applies & set(conds):
            continue
        is_proc = p["procedure"] == "yes"
        mentioned = any(w and w in t for w in p["match_words"].split(";"))
        if is_proc and not (surgery_advised or mentioned):
            continue
        gmin, gmax, pmin, pmax = (int(p[k]) for k in ("govt_min", "govt_max", "private_min", "private_max"))
        items.append({"key": p["key"], "name": p["name"], "surgery": is_proc, "mentioned": mentioned,
                      "applies": sorted(applies), "govt": f"{_fmt(gmin)} - {_fmt(gmax)}", "private": f"{_fmt(pmin)} - {_fmt(pmax)}",
                      "govt_max": gmax, "private_mid": (pmin + pmax) // 2, "pmjay": p["pmjay_coverable"], "note": p["note"]})
    # Conservative saving: the procedure the patient named; else the lowest-cost procedure for their main
    # condition; else the usual tests. Never inflate the number.
    procs = [i for i in items if i["surgery"]]
    named = [i for i in procs if i["mentioned"]]
    primary = conds[0] if conds else None
    for_primary = [i for i in procs if primary in i["applies"]]
    if named:
        basis = [min(named, key=lambda i: i["private_mid"])]
    elif procs:
        basis = [min(for_primary or procs, key=lambda i: i["private_mid"])]
    else:
        basis = [i for i in items if not i["surgery"]][:1]
    saving = sum(max(0, i["private_mid"] - i["govt_max"]) for i in basis)
    fits = [i["name"] for i in items if budget is not None and i["govt_max"] <= budget] if budget is not None else None
    return {
        "items": items, "estimated_saving": saving, "saving_basis": [i["name"] for i in basis],
        "estimated_saving_text": _fmt(saving) if saving else None, "within_budget_at_govt": fits,
        "disclaimer": "Indicative ranges for planning only. Actual cost depends on hospital and case.",
    }


# ---------------------------------------------------------------------------
# 7. Generic medicine finder (Jan Aushadhi)
# ---------------------------------------------------------------------------
def find_generics(medicines: list[str]) -> dict:
    found, unknown, monthly_saving = [], [], 0
    for m in medicines:
        key = m.strip().lower()
        match = next((g for g in GENERICS if g["brand"] == key), None) or \
            next((g for g in GENERICS if g["brand"] in key or key in g["brand"]), None)
        if not match:
            unknown.append(m)
            continue
        b, j = int(match["typical_brand_price"]), int(match["jan_aushadhi_price"])
        monthly_saving += (b - j) * 3  # assume ~3 strips a month
        found.append({"asked": m, "salt": match["salt"], "strength": match["strength"],
                      "brand_price": b, "generic_price": j, "unit": match["unit"],
                      "saving_pct": round(100 * (b - j) / b)})
    return {
        "matches": found, "not_found": unknown,
        "monthly_saving_estimate": monthly_saving,
        "where": "Nearest Pradhan Mantri Bhartiya Janaushadhi Kendra (search 'Janaushadhi Sugam' app)",
        "disclaimer": "Same salt and strength only. Do not change or stop a medicine without asking your doctor.",
    }


# ---------------------------------------------------------------------------
# 7. Second-opinion questions (before agreeing to surgery)
# ---------------------------------------------------------------------------
def second_opinion_questions(surgery_advised: bool) -> dict:
    qs = [
        "What exactly is the problem, and which report shows it?",
        "Is this urgent, or is it safe to take a few days for a second opinion?",
        "Are there non-surgical options (medicines, lifestyle changes, physiotherapy) worth trying first?",
    ]
    if surgery_advised:
        qs += [
            "What is the name of the procedure, and what is the success rate for someone like me?",
            "What are the risks, and how long is recovery before I can work again?",
            "Is this procedure covered under Ayushman Bharat at this or another hospital?",
            "Can I get the total cost in writing (package, implants or stents, medicines, stay)?",
        ]
    return {"questions": qs}


# ---------------------------------------------------------------------------
# 8. Actions: reminder (.ics) and doctor summary (PDF)
# ---------------------------------------------------------------------------
def create_reminder(title: str, details: str, days_from_now: int = 1, hour: int = 10) -> dict:
    start = (datetime.now() + timedelta(days=days_from_now)).replace(hour=hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=30)
    fid = f"reminder-{uuid.uuid4().hex[:8]}.ics"
    fmt = "%Y%m%dT%H%M%S"
    ics = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//IlaajSaathi//EN", "BEGIN:VEVENT",
        f"UID:{fid}", f"DTSTAMP:{datetime.now().strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{title}", f"DESCRIPTION:{details}",
        "BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", f"DESCRIPTION:{title}", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", ""])
    with open(os.path.join(OUT_DIR, fid), "w", encoding="utf-8") as f:
        f.write(ics)
    return {"file": fid, "when": start.strftime("%a %d %b, %I:%M %p"), "title": title}


def make_doctor_summary(profile: dict, findings: dict) -> dict:
    from .pdf_summary import build_summary_pdf  # lazy import keeps tools importable without reportlab
    fid = f"summary-{uuid.uuid4().hex[:8]}.pdf"
    build_summary_pdf(os.path.join(OUT_DIR, fid), profile, findings)
    return {"file": fid}
