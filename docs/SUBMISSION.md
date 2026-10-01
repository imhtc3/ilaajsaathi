# Final submission

## Steps
1. Push this folder to GitHub (public repo).
2. Render is already live at https://ilaajsaathi.onrender.com. Check `/api/health` shows `"llm": "openai"` (Gemini) and `"maps": "openstreetmap"`.
3. Submit using **Method 2 — API Endpoint** with the endpoint below (follow the walkthrough video in the guidelines PDF).
4. Record the 2–3 minute demo video (see DEMO_SCRIPT.md) and upload it to YouTube as Unlisted.
5. Download the pitch deck as PDF.
6. Fill the official Google Form with the answers below.

## Endpoint
- URL: https://ilaajsaathi.onrender.com/invoke
- Method: POST, JSON body
- Example: `{"input": "Severe chest pain right now with sweating", "lat": 28.60, "lng": 77.22}`
- Health check: https://ilaajsaathi.onrender.com/api/health

## Form answers

**Project name:** IlaajSaathi

**Team members:** Prashant Yadav (solo)

**Selected domain:** HealthTech

**Problem statement:**
Families told they need costly treatment, like an angioplasty, a knee replacement or kidney stone surgery, often pay private hospital prices or delay care, because they don't know about free government consults, Ayushman Bharat cover, nearby government hospitals or generic medicines. In emergencies like a heart attack or stroke, they lose critical time going to the nearest hospital instead of one that has the right facility.

**Solution overview:**
IlaajSaathi is an AI agent that a patient or family member can talk to in Hindi or English, by voice or text. In an emergency it identifies the facility the symptoms need (cath lab, stroke care, trauma centre) and routes them to the nearest hospital that has it, with a Call 108 button, travel time and directions. It then builds the affordable follow-up plan. For non-emergencies it finds free consults (eSanjeevani), estimates Ayushman Bharat eligibility, lists the nearest government hospitals with the right department, compares government and private costs, finds Jan Aushadhi generic medicines and prepares questions for a second opinion. It finishes by creating a doctor summary PDF and a reminder.

**Agent workflow / architecture:**
Understand (extract condition, procedure, quoted cost, budget, age, location, medicines from Hindi/English) → Safety gate (rule-based, cannot be skipped) → Emergency routing, or ask once for missing location/budget → Plan which tools to run (Gemini planner with guardrails, rule planner as fallback) → Use tools (maps, eligibility, hospitals, costs, generics, consult options, second-opinion questions) → Act (doctor summary PDF, calendar reminder) → Deliver a reply in the user's language with a visible step-by-step trace.

**Technology stack:**
Python (standard-library HTTP server), reportlab, Gemini API, OpenStreetMap (Nominatim, Overpass, OSRM), optional Google Maps Platform, browser Web Speech and Geolocation APIs, Docker, Render.

**GitHub repository:** (add your repo link)

**Working demo:** https://ilaajsaathi.onrender.com

**Demo video:** (add your YouTube link after recording)

**Pitch deck:** download as PDF from the deck link and upload, or share the link.
