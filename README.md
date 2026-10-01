# IlaajSaathi — safe, affordable treatment agent for Bharat

**Domain:** HealthTech · **Hackathon:** BharatAgentic (powered by aiKart)

> "Doctor ne operation bola hai, par paise nahi hain." Families told they need an angioplasty, a knee
> replacement or kidney stone surgery often pay private prices, or delay care, because nobody tells them
> about free consults, Ayushman Bharat cover or government hospitals nearby. And in an emergency, people
> lose precious minutes going to a hospital that can't treat them. IlaajSaathi fixes both.

## What it does
A patient (or family member) types or speaks in Hindi, Hinglish or English: the problem, where they are
(or taps **Use my location**), and their budget.

**Emergency? Route, don't stop.** A rule-based safety gate runs first. If the symptoms are an emergency it
works out the *facility* needed and sends the patient to the nearest hospital that has it:

| Symptoms | Facility it routes to |
|---|---|
| Chest pain with sweating, breathlessness, arm/jaw pain | 24x7 cath lab (heart attack care) |
| Face drooping, slurred speech, one-sided weakness | CT scan + stroke care |
| Loss of bladder control, worsening leg weakness | Emergency spine/brain surgery |
| Accident, head injury, heavy bleeding | Trauma centre |
| Severe breathlessness, fainting | 24x7 emergency |

It shows travel time, a **Call 108** button, directions and a map, the nearest *government* option, and
the patient's right to emergency stabilisation. Then it keeps going: Ayushman Bharat check, government
hospitals and costs for treatment *after* the emergency, and a doctor summary PDF.

**Not an emergency?** It asks once for anything missing (location, budget), plans, then uses tools:
free eSanjeevani consult, Ayushman Bharat eligibility estimate, nearest government hospitals with the right
specialist and travel times, government vs private cost comparison, Jan Aushadhi generic medicines,
second-opinion questions, doctor summary PDF and a calendar reminder.

It never diagnoses or prescribes, and never tells anyone to stop a medicine.

## APIs used
| Need | Primary | Free fallback | Offline fallback |
|---|---|---|---|
| City/address → coordinates | Google **Geocoding API** | OpenStreetMap Nominatim | City centres |
| Nearby hospitals with a facility | Google **Places API (New)** Text Search | OpenStreetMap Overpass | Curated government hospital list (6 cities) |
| Travel time with traffic | Google **Routes API** (Route Matrix) | — | Distance-based estimate |
| Directions | Google Maps directions links (no key needed) | | |
| Map preview | OpenStreetMap embed (no key) | | |
| Patient location | Browser Geolocation API | | |
| Voice input | Browser Web Speech API (hi-IN, en-IN) | | |
| Understanding, planning, Hindi replies, prescription photos | Claude or any OpenAI-compatible LLM | | Rule-based |

**Google setup (5 minutes):** Google Cloud console → create a project → enable *Places API (New)*,
*Geocoding API* and *Routes API* → create an API key → restrict it to those three APIs →
`export GOOGLE_MAPS_API_KEY=...`. New Google Cloud accounts get free monthly credit, enough for a hackathon.

## Run it
```bash
pip install -r requirements.txt        # only dependency: reportlab
python -m app.server                    # open http://localhost:8000
python -m unittest discover tests       # 13 tests, no keys or network needed
```
Optional keys go in the environment (see `.env.example`).

## Docker
```bash
docker build -t ilaajsaathi .
docker run -p 8000:8000 -e GOOGLE_MAPS_API_KEY=$GOOGLE_MAPS_API_KEY -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY ilaajsaathi
```

## API
`POST /invoke` — `{"input": "...", "session_id": "optional", "lat": 28.6, "lng": 77.2}` →
`{"output": "...", "status": "need_info|plan_ready|urgent", "need": "location|budget|null", "plan": {...}, "trace": [...], "session_id": "..."}`

```bash
curl -X POST localhost:8000/invoke -H "Content-Type: application/json" \
  -d '{"input":"Severe chest pain right now with sweating", "lat":28.60, "lng":77.22}'
```
Also: `POST /api/chat` (same, field `message`, used by the UI), `GET /api/health`, `GET /files/<name>`.

## Deploy (API endpoint submission)
Render / Railway: new Web Service from this repo → Docker → add your keys as env vars.
Endpoint: `https://<app>.onrender.com/invoke`. HTTPS is required for the browser location button.

## Project layout
```
app/agent.py        orchestrator: understand → safety gate → plan → tools → act → deliver
app/tools.py        10 tools: safety, emergency routing, eligibility, consults, hospitals, costs, generics, questions, PDF, reminder
app/geo.py          maps layer: Google Geocoding / Places / Routes → OpenStreetMap → offline
app/llm.py          optional LLM (Claude or any OpenAI-compatible API), stdlib only
app/pdf_summary.py  doctor summary PDF
app/server.py       HTTP server + API (Python standard library)
app/static/         web app: voice, location, prescription upload, emergency card with Call 108 + directions
app/data/           curated government hospitals (6 cities, with facilities), procedure costs, generic medicines
agent.yaml          agent manifest (align field names with the aiKart guide)
docs/               architecture, demo script, pitch deck content, submission checklist
```

## Data and honesty notes
Curated hospital facilities and coordinates are for the demo; the app tells users to call ahead to confirm.
Cost ranges and medicine prices are **indicative planning figures**, labelled in the app; replace them with
official PM-JAY package rates and the PMBI Jan Aushadhi list for production. Eligibility is an estimate;
the official check (beneficiary.nha.gov.in / 14555) is always shown.
