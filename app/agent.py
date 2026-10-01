"""IlaajSaathi orchestrator.

Understand -> Reason -> Plan -> Use tools -> Act -> Deliver

* Understand: a structured patient profile from free text (Hindi, Hinglish or English) + device location.
* Reason:     safety gate first. Emergencies are ROUTED (nearest hospital with the facility the symptoms
              need), never just stopped; the affordable follow-up plan is still built underneath.
              Otherwise ask once for what's missing (location/city, budget).
* Plan:       choose tools and why (LLM planner if a key is set, rule planner otherwise); guardrails enforce
              the safety steps.
* Use tools / Act: maps, schemes, costs, generics; creates a doctor summary PDF and a reminder.
* Deliver:    a short reply in the user's language + a structured plan for the UI.
"""
from __future__ import annotations

import re
import time
import uuid

from . import geo, llm, tools

SESSIONS: dict[str, dict] = {}

CITY_ALIASES = {
    "delhi": "delhi", "new delhi": "delhi", "दिल्ली": "delhi",
    "lucknow": "lucknow", "लखनऊ": "lucknow",
    "patna": "patna", "पटना": "patna",
    "mumbai": "mumbai", "bombay": "mumbai", "मुंबई": "mumbai",
    "bengaluru": "bengaluru", "bangalore": "bengaluru", "बेंगलुरु": "bengaluru",
    "jaipur": "jaipur", "जयपुर": "jaipur",
}
# Latin words match on word boundaries; Devanagari words match as substrings.
CONDITION_WORDS = {
    "heart": ["heart", "cardiac", "chest pain", "chest", "blockage", "blocked arter", "angioplasty", "angiography",
              "angiogram", "stent", "bypass", "cabg", "dil", "seene", "दिल", "हृदय", "सीने", "छाती", "ब्लॉकेज", "हार्ट"],
    "knee": ["knee", "knees", "ghutna", "ghutne", "घुटन"],
    "kidney": ["kidney", "stone", "stones", "pathri", "पथरी", "गुर्दे", "किडनी"],
    "eye": ["cataract", "motiyabind", "eye", "eyes", "मोतियाबिंद", "आंख"],
    "back": ["back pain", "backache", "lower back", "spine", "slip disc", "sciatica", "kamar", "कमर", "पीठ"],
    "neck": ["neck", "cervical", "gardan", "गर्दन"],
    "hand": ["hand", "hands", "wrist", "haath", "हाथ"],
    "leg": ["leg", "legs", "पैर"],
    "shoulder": ["shoulder", "kandha", "कंधा", "कंधे"],
}
SURGERY_WORDS = [r"surgery", r"operation", r"opration", r"operate", r"angioplasty", r"\bstent", r"bypass",
                 r"replacement", r"ऑपरेशन", r"सर्जरी", r"ओपरेशन", r"बदलने", r"एंजियोप्लास्टी", r"बायपास"]
HINGLISH = ["hai", "mujhe", "mera", "meri", "dard", "nahi", "kya", "bahut", "paisa", "ilaj", "ilaaj", "bola", "hain"]

TOOL_NAMES = ["red_flag_check", "route_emergency", "teleconsult_options", "check_pmjay_eligibility", "find_hospitals",
              "estimate_costs", "find_generics", "second_opinion_questions", "make_doctor_summary", "create_reminder"]


# ---------------------------------------------------------------------------
# Understand
# ---------------------------------------------------------------------------
def _amount(s: str) -> int | None:
    s = s.lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(lakh|lac|लाख)", s)
    if m:
        return int(float(m.group(1)) * 100000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(k|hazaar|hazar|thousand|हजार|हज़ार)\b", s)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d{3,7})", s)
    return int(m.group(1)) if m else None


BUDGET_KW = r"(budget|spend|afford|kharch kar|kharch|खर्च|only have|have only|bas|बस)"
QUOTE_KW = r"(quoted|quote|estimate|will cost|asked for|cost of|charges?|bataya|बताया|मांग)"


def _budget_and_quote(text: str) -> tuple[int | None, int | None]:
    t = text.lower().replace(",", "")
    budget = quote = None
    m = re.search(BUDGET_KW + r"[^0-9]{0,25}([\d.]+\s*(?:lakh|lac|लाख|k\b|hazaar|hazar|thousand|हजार|हज़ार)?)", t)
    if m:
        budget = _amount(m.group(2))
    if budget is None:  # Hindi order: "15000 रुपये तक खर्च"
        m = re.search(r"([\d.]+\s*(?:lakh|lac|लाख|k|hazaar|हजार|हज़ार)?)\s*(?:rs|rupees?|रुपये|rupaye)?\s*(?:tak|तक)?\s*" + BUDGET_KW, t)
        if m:
            budget = _amount(m.group(1))
    m = re.search(r"([\d.]+\s*(?:lakh|lac|लाख))\s*(?:rs|rupees?|रुपये)?\s*" + QUOTE_KW, t)
    if m:
        quote = _amount(m.group(1))
    else:
        m = re.search(QUOTE_KW + r"[^0-9.।]{0,20}([\d.]+\s*(?:lakh|lac|लाख|k\b|hazaar|हजार)?)", t)
        if m:
            quote = _amount(m.group(2))
    if budget is None and quote is None:  # a lone amount with a currency marker = budget
        m = re.search(r"(?:₹|rs\.?|inr|rupees?)\s*(\d{3,7})|(\d{3,7})\s*(?:rs|rupees?|रुपये|rupaye)", t)
        if m:
            budget = int(m.group(1) or m.group(2))
    return budget, quote


def _has_word(t: str, w: str) -> bool:
    if re.search(r"[\u0900-\u097F]", w):
        return w in t
    return re.search(rf"\b{re.escape(w)}", t) is not None


def _rules_extract(text: str) -> dict:
    t = " " + text.lower() + " "
    p: dict = {}
    pos = {}
    for k, words in CONDITION_WORDS.items():
        hits = [m.start() for w in words for m in [re.search(rf"\b{re.escape(w)}" if not re.search(r"[\u0900-\u097F]", w) else re.escape(w), t)] if m]
        if hits:
            pos[k] = min(hits)
    if pos:
        p["conditions"] = sorted(pos, key=pos.get)  # order of mention
    if any(re.search(w, t) for w in SURGERY_WORDS):
        p["surgery_advised"] = True
    for alias, city in CITY_ALIASES.items():
        if alias in t:
            p["city"] = city
            break
    else:
        m = re.search(r"\b(?:i live in|living in|i stay in|i am from|i'm from|city is|city:)\s+([a-z]{4,20})\b", t)
        if m and m.group(1) not in {"pain", "the", "this", "that", "both"}:
            p["city"] = m.group(1)
    budget, quote = _budget_and_quote(text)
    if budget:
        p["budget"] = budget
    if quote:
        p["quoted_cost"] = quote
    m = re.search(r"(?:age|aged|umar|उम्र)\D{0,4}(\d{1,3})", t) or \
        re.search(r"(\d{1,3})\s*(?:years? old|yrs? old|yo\b|saal ka|saal ki|saal ke|साल)", t)
    if m and 0 < int(m.group(1)) < 110:
        p["age"] = int(m.group(1))
    m = re.search(r"(\d+)\s*(months?|years?|weeks?|days?|mahine|saal|महीने|साल|दिन)\s*(?:se|से|since|from)", t)
    if m:
        p["duration"] = f"{m.group(1)} {m.group(2)}"
    meds = [g["brand"] for g in tools.GENERICS if _has_word(t, g["brand"])]
    meds = [m for m in meds if not any(m != o and m in o for o in meds)]
    if meds:
        p["medicines"] = meds
    for card in ["antyodaya", "aay", "bpl", "priority", "phh"]:
        if re.search(rf"\b{card}\b", t):
            p["ration_card"] = card
    m = re.search(r"(?:income|earn|kamata|kamai|salary)\D{0,15}(\d{3,7})", t)
    if m:
        p["monthly_income"] = int(m.group(1))
    return p


def _language(text: str) -> str:
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    words = re.findall(r"[a-z]+", text.lower())
    return "hinglish" if sum(w in HINGLISH for w in words) >= 2 else "en"


EXTRACT_SYSTEM = """You extract a patient profile for an Indian affordable-care assistant.
The user may write in Hindi, Hinglish or English. Never diagnose.
Return JSON with these keys (null when unknown):
conditions (array, most important first, from: heart, knee, kidney, eye, back, neck, hand, leg, shoulder),
surgery_advised (bool: a doctor advised surgery or a procedure such as angioplasty, bypass, replacement),
city (lowercase English), budget (integer rupees the patient can spend), quoted_cost (integer rupees a hospital quoted),
age (int), duration (short string), medicines (array of names as written),
ration_card (one of: aay, bpl, priority, apl, none), monthly_income (int), name (string),
story_en (2-3 sentence first-person English summary of what the patient said)."""
LLM_KEYS = {"conditions", "surgery_advised", "city", "budget", "quoted_cost", "age", "duration", "medicines",
            "ration_card", "monthly_income", "name", "story_en"}


def understand(text: str, session: dict, image_b64: str | None = None, image_type: str = "image/jpeg",
               lat: float | None = None, lng: float | None = None) -> tuple[dict, str]:
    profile = session["profile"]
    found = _rules_extract(text)
    source = "rules"
    llm_p = llm.complete_json(EXTRACT_SYSTEM, f"Patient message:\n{text}") if llm.provider() else None
    if llm_p:
        source = llm.provider()
        for k, v in llm_p.items():
            if k in LLM_KEYS and v not in (None, "", [], "none"):
                if k == "city" and isinstance(v, str):
                    v = CITY_ALIASES.get(v.strip().lower(), v.strip().lower())
                if k == "conditions":
                    v = [c for c in v if c in CONDITION_WORDS] or found.get("conditions")
                if v:
                    found[k] = v
    if image_b64 and llm.provider():
        rx = llm.complete_json("Read this prescription or report photo. Extract medicine names only.",
                               'Return {"medicines": ["name", ...]}', image_b64=image_b64, image_type=image_type)
        if rx and rx.get("medicines"):
            found["medicines"] = list(dict.fromkeys((found.get("medicines") or []) + rx["medicines"]))
            source += "+vision"
    for k, v in found.items():
        if k in {"conditions", "medicines"}:
            profile[k] = list(dict.fromkeys((profile.get(k) or []) + list(v)))
        else:
            profile[k] = v
    if lat is not None and lng is not None:
        profile["lat"], profile["lng"] = float(lat), float(lng)
        source += "+gps"
    profile["raw_text"] = (profile.get("raw_text", "") + " " + text).strip()
    if "lang" not in profile or _language(text) != "en":
        profile["lang"] = _language(text)
    return profile, source


def _has_location(p: dict) -> bool:
    return bool(p.get("city")) or (p.get("lat") is not None and p.get("lng") is not None)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------
def rule_plan(profile: dict, urgent: bool) -> list[dict]:
    if urgent:
        return [
            {"tool": "red_flag_check", "why": "Safety first: check for emergency warning signs."},
            {"tool": "route_emergency", "why": "Emergency: find the nearest hospital with the facility these symptoms need."},
            {"tool": "check_pmjay_eligibility", "why": "So money doesn't delay care: check Ayushman Bharat cover."},
            {"tool": "find_hospitals", "why": "Line up the nearest government hospitals for affordable follow-up care."},
            {"tool": "estimate_costs", "why": "Show government vs private costs for the likely treatment."},
            {"tool": "make_doctor_summary", "why": "One-page summary to hand to the emergency doctor."},
        ]
    steps = [{"tool": "red_flag_check", "why": "Safety first: check for emergency warning signs."},
             {"tool": "teleconsult_options", "why": "A free doctor opinion is the safest minimal-cost next step."},
             {"tool": "check_pmjay_eligibility", "why": "Check if Ayushman Bharat can pay for treatment."},
             {"tool": "find_hospitals", "why": "Find the nearest government hospitals with the right specialist."},
             {"tool": "estimate_costs", "why": "Compare government vs private costs for tests and treatment."}]
    if profile.get("medicines"):
        steps.append({"tool": "find_generics", "why": "Check affordable Jan Aushadhi generics for current medicines."})
    steps.append({"tool": "second_opinion_questions",
                  "why": "Surgery was advised; prepare questions for a second opinion." if profile.get("surgery_advised")
                  else "Prepare the right questions for the doctor visit."})
    steps.append({"tool": "make_doctor_summary", "why": "One-page summary so the next doctor visit is faster."})
    steps.append({"tool": "create_reminder", "why": "Turn the plan into action with a dated reminder."})
    return steps


PLAN_SYSTEM = f"""You are the planner for IlaajSaathi, an agent that helps people in India get safe treatment at minimal cost.
Available tools: {", ".join(TOOL_NAMES)}.
Given a patient profile and whether there is an emergency, choose the tools to run in order, each with a one-line reason.
Return JSON: {{"steps": [{{"tool": "...", "why": "..."}}]}}"""


def plan(profile: dict, urgent: bool) -> tuple[list[dict], str]:
    steps, source = None, "rules"
    if llm.provider():
        safe = {k: v for k, v in profile.items() if k not in {"raw_text", "lat", "lng"}}
        out = llm.complete_json(PLAN_SYSTEM, f"Emergency: {urgent}\nProfile: {safe}")
        if out and isinstance(out.get("steps"), list):
            steps = [s for s in out["steps"] if isinstance(s, dict) and s.get("tool") in TOOL_NAMES]
            source = llm.provider()
    if not steps:
        steps = rule_plan(profile, urgent)
    # Guardrails: safety check first; emergencies always routed first; mandatory follow-up steps present.
    steps = [s for s in steps if s["tool"] not in {"red_flag_check", "route_emergency"}]
    head = [{"tool": "red_flag_check", "why": "Safety first: check for emergency warning signs."}]
    if urgent:
        head.append({"tool": "route_emergency", "why": "Emergency: nearest hospital with the facility these symptoms need."})
    must = [("check_pmjay_eligibility", "Check if Ayushman Bharat can pay."),
            ("find_hospitals", "Nearest government hospitals for affordable care."),
            ("make_doctor_summary", "One-page summary for the doctor.")]
    if not urgent:
        must += [("teleconsult_options", "A free doctor opinion is the safest minimal-cost next step."),
                 ("create_reminder", "Turn the plan into action with a dated reminder.")]
    final, seen = [], set()
    for s in head + steps:
        if s["tool"] not in seen:
            final.append(s)
            seen.add(s["tool"])
    for tool, why in must:
        if tool not in seen:
            final.append({"tool": tool, "why": why})
            seen.add(tool)
    if urgent:  # no reminders or shopping-around during an emergency
        final = [s for s in final if s["tool"] not in {"create_reminder", "teleconsult_options", "find_generics"}]
    elif profile.get("medicines") and "find_generics" not in seen:
        final.insert(-2, {"tool": "find_generics", "why": "Check affordable generic versions of current medicines."})
    return final, source


# ---------------------------------------------------------------------------
# Act
# ---------------------------------------------------------------------------
def run_tool(name: str, profile: dict, results: dict) -> dict:
    conds = profile.get("conditions") or []
    rf = results.get("red_flag_check") or {}
    if name == "route_emergency":
        return tools.route_emergency(profile, rf.get("facility_needed") or "emergency")
    if name == "teleconsult_options":
        return tools.teleconsult_options(profile)
    if name == "check_pmjay_eligibility":
        return tools.check_pmjay_eligibility(profile)
    if name == "find_hospitals":
        if not conds and rf.get("facility_needed") == "cath_lab":
            conds = ["heart"]
        return tools.find_hospitals(profile, conds)
    if name == "estimate_costs":
        text = profile.get("raw_text", "")
        # After a heart attack, the usual next steps are angiography and often angioplasty: show those costs.
        if rf.get("facility_needed") == "cath_lab":
            text += " angiography angioplasty"
        return tools.estimate_costs(conds, bool(profile.get("surgery_advised")), profile.get("budget"), text)
    if name == "find_generics":
        return tools.find_generics(profile.get("medicines") or [])
    if name == "second_opinion_questions":
        return tools.second_opinion_questions(bool(profile.get("surgery_advised")))
    if name == "make_doctor_summary":
        return tools.make_doctor_summary(profile, {"red_flags": rf, "questions": results.get("second_opinion_questions")})
    if name == "create_reminder":
        return tools.create_reminder("Book free eSanjeevani consult",
                                     "Open esanjeevani.mohfw.gov.in. Keep your IlaajSaathi summary PDF and reports ready.")
    raise ValueError(name)


def _brief(name: str, out: dict) -> str:
    if name == "red_flag_check":
        if out["urgent"]:
            return "EMERGENCY: " + ", ".join(f["label"] for f in out["red_flags"] if f["urgent"]) + \
                f" -> needs {out['facility_label']}"
        return f"{len(out['red_flags'])} sign(s) to mention to a doctor" if out["red_flags"] else "No emergency signs found"
    if name == "route_emergency":
        b = out.get("best")
        if b:
            return f"Go to {b['name']} ({b.get('minutes', '?')} min) - maps: {out['maps']}"
        return "No location yet - asked user to share location; 108 advised"
    if name == "check_pmjay_eligibility":
        return f"Ayushman Bharat: {out['status']}"
    if name == "find_hospitals":
        return f"{len(out['hospitals'])} hospital(s) near {out.get('origin') or 'you'} (maps: {out['maps']})" \
            if out["hospitals"] else out["note"]
    if name == "estimate_costs":
        return f"Possible saving at a government hospital: {out['estimated_saving_text']}" \
            if out.get("estimated_saving_text") else f"{len(out['items'])} cost items compared"
    if name == "find_generics":
        return f"{len(out['matches'])} generic match(es), save about Rs {out['monthly_saving_estimate']:,}/month"
    if name == "second_opinion_questions":
        return f"{len(out['questions'])} questions prepared"
    if name == "make_doctor_summary":
        return "Summary PDF created"
    if name == "create_reminder":
        return f"Reminder set: {out['when']}"
    if name == "teleconsult_options":
        return f"{len(out['options'])} free or minimal-cost consult routes"
    return "done"


# ---------------------------------------------------------------------------
# Deliver
# ---------------------------------------------------------------------------
T = {
    "en": {
        "ask_loc": "Where are you? Tap \"Use my location\" or type your city or district, and I'll find the nearest government hospitals.",
        "ask_budget": "Roughly how much can you spend on treatment? An approximate amount is fine (for example, Rs 20,000).",
        "em_go": "This needs emergency care now. Go to {name}, which has {fac}, about {min} minutes away, or call 108 for a free ambulance.",
        "em_noloc": "This needs emergency care now. Call 108 for a free ambulance. Tap \"Use my location\" or tell me your city, and I'll find the nearest hospital with {fac}.",
        "em_unconfirmed": "This needs emergency care now. Call 108 for a free ambulance; the ambulance team knows which hospitals have {fac}. The nearest large hospital is {name}, about {min} minutes away. Call them first to check they can treat this.",
        "em_money": "Don't wait to arrange money: hospitals must stabilise emergencies, and Ayushman Bharat cards are accepted at empanelled hospitals. Affordable options for treatment after the emergency are below.",
        "intro": "Here's your affordable treatment plan.",
        "consult": "Start with a free video consult on eSanjeevani, then see the specialist at a government hospital OPD.",
        "near": "Nearest government option: {name}{mins}.",
        "ayush": {"likely": "You are likely eligible for Ayushman Bharat (free treatment up to Rs 5 lakh a year). Confirm at beneficiary.nha.gov.in or call 14555.",
                  "possible": "You may be eligible for Ayushman Bharat (free treatment up to Rs 5 lakh a year). Check at beneficiary.nha.gov.in or call 14555.",
                  "unknown": "Check whether Ayushman Bharat covers you (free treatment up to Rs 5 lakh a year) at beneficiary.nha.gov.in or call 14555."},
        "save": "Getting {what} at a government hospital could save about {x}.",
        "gen": "Switching to Jan Aushadhi generics could save about Rs {x:,} a month.",
        "surg": "Before agreeing to the procedure, get a second opinion. I've listed the questions to ask.",
        "end": "Your doctor summary and reminder are ready below. I don't diagnose; a doctor decides your treatment.",
    },
    "hi": {
        "ask_loc": "आप कहां हैं? \"मेरी लोकेशन\" बटन दबाएं या अपना शहर/ज़िला लिखें, मैं पास के सरकारी अस्पताल ढूंढूंगा।",
        "ask_budget": "इलाज पर लगभग कितना खर्च कर सकते हैं? अंदाज़ा भी चलेगा (जैसे 20,000 रुपये)।",
        "em_go": "यह इमरजेंसी है। अभी {name} जाएं, वहां {fac} की सुविधा है, लगभग {min} मिनट दूर। या 108 पर कॉल करें, एम्बुलेंस मुफ़्त है।",
        "em_noloc": "यह इमरजेंसी है। अभी 108 पर कॉल करें, एम्बुलेंस मुफ़्त है। \"मेरी लोकेशन\" दबाएं या अपना शहर बताएं, मैं {fac} वाला नज़दीकी अस्पताल ढूंढूंगा।",
        "em_unconfirmed": "यह इमरजेंसी है। अभी 108 पर कॉल करें, एम्बुलेंस मुफ़्त है; एम्बुलेंस टीम जानती है कि {fac} की सुविधा कहां है। सबसे नज़दीकी बड़ा अस्पताल {name} है, लगभग {min} मिनट दूर। जाने से पहले फ़ोन करके पक्का करें।",
        "em_money": "पैसों का इंतज़ाम करने में देर न करें: अस्पताल को इमरजेंसी में मरीज़ को संभालना होता है, और आयुष्मान कार्ड पैनल वाले अस्पतालों में चलता है। इमरजेंसी के बाद के किफ़ायती विकल्प नीचे हैं।",
        "intro": "आपका किफ़ायती इलाज प्लान तैयार है।",
        "consult": "पहले eSanjeevani पर मुफ़्त वीडियो परामर्श लें, फिर सरकारी अस्पताल की OPD में विशेषज्ञ को दिखाएं।",
        "near": "सबसे नज़दीकी सरकारी अस्पताल: {name}{mins}।",
        "ayush": {"likely": "आप आयुष्मान भारत (साल में 5 लाख तक मुफ़्त इलाज) के लिए संभवतः पात्र हैं। beneficiary.nha.gov.in पर पक्का करें या 14555 पर कॉल करें।",
                  "possible": "आप आयुष्मान भारत (साल में 5 लाख तक मुफ़्त इलाज) के लिए पात्र हो सकते हैं। beneficiary.nha.gov.in पर जांचें या 14555 पर कॉल करें।",
                  "unknown": "beneficiary.nha.gov.in पर या 14555 पर कॉल करके जांचें कि आयुष्मान भारत (साल में 5 लाख तक मुफ़्त इलाज) में आप शामिल हैं या नहीं।"},
        "save": "यही इलाज सरकारी अस्पताल में कराने से लगभग {x} बच सकते हैं।",
        "gen": "जन औषधि की जेनेरिक दवाओं से हर महीने लगभग {x:,} रुपये बच सकते हैं।",
        "surg": "प्रक्रिया/ऑपरेशन के लिए हां कहने से पहले दूसरी राय ज़रूर लें। पूछने वाले सवाल नीचे दिए हैं।",
        "end": "डॉक्टर के लिए सारांश और रिमाइंडर नीचे हैं। मैं बीमारी तय नहीं करता, इलाज डॉक्टर तय करेंगे।",
    },
}
FAC_HI = {"cath_lab": "24 घंटे हार्ट अटैक इलाज (कैथ लैब)", "stroke": "CT स्कैन और स्ट्रोक इलाज",
          "neurosurgery": "इमरजेंसी स्पाइन/ब्रेन सर्जरी", "trauma": "ट्रॉमा सेंटर", "emergency": "24 घंटे इमरजेंसी"}


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s and not s[:4].isupper() else s


def template_reply(profile: dict, r: dict) -> str:
    lang = "hi" if profile.get("lang") == "hi" else "en"
    t = T[lang]
    rf = r.get("red_flag_check") or {}
    lines = []
    if rf.get("urgent"):
        em = r.get("route_emergency") or {}
        fac = FAC_HI.get(rf["facility_needed"], "") if lang == "hi" else rf["facility_label"]
        best = em.get("best")
        if best and best.get("tier", 0) == 0:
            lines.append(t["em_go"].format(name=best["name"], fac=fac, min=best.get("minutes", "?")))
        elif best:
            lines.append(t["em_unconfirmed"].format(name=best["name"], fac=fac, min=best.get("minutes", "?")))
        else:
            lines.append(t["em_noloc"].format(fac=fac))
        lines.append(t["em_money"])
        return " ".join(lines)
    lines += [t["intro"], t["consult"]]
    h = (r.get("find_hospitals") or {}).get("hospitals") or []
    if h:
        mins = f" ({h[0]['minutes']} min)" if h[0].get("minutes") else ""
        lines.append(t["near"].format(name=h[0]["name"], mins=mins))
    el = r.get("check_pmjay_eligibility")
    if el:
        lines.append(t["ayush"].get(el["status"], t["ayush"]["unknown"]))
    c = r.get("estimate_costs") or {}
    if c.get("estimated_saving_text"):
        x = c["estimated_saving_text"]
        if lang == "hi":
            x = x.replace("Rs ", "").replace(" lakh", " लाख") + " रुपये"
        lines.append(t["save"].format(x=x, what=_lower_first((c.get("saving_basis") or ["treatment"])[0])))
    g = r.get("find_generics") or {}
    if g.get("monthly_saving_estimate"):
        lines.append(t["gen"].format(x=g["monthly_saving_estimate"]))
    if profile.get("surgery_advised"):
        lines.append(t["surg"])
    lines.append(t["end"])
    return " ".join(lines)


REPLY_SYSTEM = """You are IlaajSaathi, a calm, practical assistant helping people in India get safe treatment at minimal cost.
Write the final reply using ONLY the facts in the tool results. Reply in the same language and script the patient used
(Hindi, Hinglish or English). 4-7 short sentences, plain words, no markdown headings. Never diagnose or prescribe; never tell
anyone to stop a medicine. If there is an emergency: FIRST tell them to go now to the named hospital (say which facility it has
and the travel time) or call 108 for a free ambulance, and not to delay over money; THEN briefly mention the affordable options
for treatment afterwards. Use words like "affordable", "free" or "minimal cost", never "cheap"."""


def deliver(profile: dict, results: dict) -> tuple[str, str]:
    if llm.provider():
        compact = {k: v for k, v in results.items() if k != "teleconsult_options"}
        txt = llm.complete(REPLY_SYSTEM, f"Patient said: {profile.get('raw_text')}\n\nTool results: {compact}", max_tokens=600)
        if txt:
            return txt.strip(), llm.provider()
    return template_reply(profile, results), "template"


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------
def handle(message: str, session_id: str | None = None, image_b64: str | None = None, image_type: str = "image/jpeg",
           lat: float | None = None, lng: float | None = None) -> dict:
    sid = session_id if session_id in SESSIONS else uuid.uuid4().hex[:12]
    session = SESSIONS.setdefault(sid, {"profile": {}, "asked": set()})
    trace = []

    def log(phase, title, detail="", tool=None, ms=None):
        trace.append({"phase": phase, "title": title, "detail": detail, "tool": tool, "ms": ms})

    t0 = time.time()
    profile, src = understand(message, session, image_b64, image_type, lat, lng)
    log("understand", "Understood the problem", f"{_describe(profile)} (via {src})", ms=int((time.time() - t0) * 1000))

    rf = tools.red_flag_check(profile.get("raw_text", ""))
    log("reason", "Safety check", _brief("red_flag_check", rf), tool="red_flag_check")
    lang = "hi" if profile.get("lang") == "hi" else "en"
    engine = {"llm": llm.provider() or "rules", "maps": geo.maps_source()}

    if not rf["urgent"]:  # emergencies never wait for follow-up questions
        for field, key, ok in [("location", "ask_loc", _has_location(profile)),
                               ("budget", "ask_budget", profile.get("budget") is not None)]:
            if not ok and field not in session["asked"]:
                session["asked"].add(field)
                log("reason", f"Missing {field}", "Asking one follow-up question before planning.")
                return {"session_id": sid, "status": "need_info", "need": field, "reply": T[lang][key],
                        "profile": _public(profile), "trace": trace, "plan": None, "engine": engine}

    steps, psrc = plan(profile, rf["urgent"])
    log("plan", "Made a plan", " -> ".join(s["tool"] for s in steps) + f" (via {psrc})")

    results: dict = {"red_flag_check": rf}
    for s in steps:
        if s["tool"] == "red_flag_check":
            continue
        ts = time.time()
        try:
            out = run_tool(s["tool"], profile, results)
            results[s["tool"]] = out
            phase = "act" if s["tool"] in {"make_doctor_summary", "create_reminder", "route_emergency"} else "tool"
            log(phase, s["why"], _brief(s["tool"], out), tool=s["tool"], ms=int((time.time() - ts) * 1000))
        except Exception as e:
            log("tool", s["why"], f"failed: {e}", tool=s["tool"])

    reply, rsrc = deliver(profile, results)
    log("deliver", "Wrote the answer", f"via {rsrc}")
    saving = (results.get("estimate_costs") or {}).get("estimated_saving", 0) + \
        12 * (results.get("find_generics") or {}).get("monthly_saving_estimate", 0)
    needs_loc = bool((results.get("route_emergency") or {}).get("needs_location"))
    return {"session_id": sid, "status": "urgent" if rf["urgent"] else "plan_ready", "reply": reply,
            "need": "location" if needs_loc else None, "profile": _public(profile), "trace": trace, "plan": results,
            "estimated_total_saving": saving, "engine": engine}


def _describe(p: dict) -> str:
    bits = []
    if p.get("conditions"):
        bits.append("concern: " + ", ".join(p["conditions"]))
    if p.get("duration"):
        bits.append(f"for {p['duration']}")
    if p.get("surgery_advised"):
        bits.append("procedure advised")
    if p.get("quoted_cost"):
        bits.append(f"quoted Rs {p['quoted_cost']:,}")
    if p.get("lat") is not None:
        bits.append("location shared")
    if p.get("city"):
        bits.append(str(p["city"]).title())
    if p.get("budget"):
        bits.append(f"budget Rs {p['budget']:,}")
    if p.get("age"):
        bits.append(f"age {p['age']}")
    if p.get("medicines"):
        bits.append("takes " + ", ".join(p["medicines"]))
    if p.get("ration_card"):
        bits.append(f"{p['ration_card'].upper()} ration card")
    return "; ".join(bits) or "no details yet"


def _public(p: dict) -> dict:
    return {k: v for k, v in p.items() if k != "raw_text"}
