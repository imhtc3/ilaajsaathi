# IlaajSaathi

A health agent that helps people in India find the safest way to get treated at the lowest cost they can manage. You tell it what's wrong, where you are and how much you can spend (in Hindi or English, typed or spoken), and it works out the rest.

Built for the BharatAgentic Hackathon (aiKart), HealthTech track.

**Live demo:** https://ilaajsaathi.onrender.com


(It's on Render's free plan, so the first load after a while can take a minute to wake up.)

## Why I made this

When a doctor says "you need an angioplasty, it'll cost 3 lakh", most families either borrow money or put it off. A lot of them never find out that:

- they can get a free video consult with a government doctor on eSanjeevani
- they might already be covered by Ayushman Bharat (5 lakh a year, and everyone over 70 is covered now)
- the same procedure at a government hospital nearby costs a fraction of the private quote
- the medicines they buy every month have generic versions at Jan Aushadhi stores for much less

All of this information exists, it's just spread across different portals that you have to already know about.

The other problem is emergencies. If someone is having a heart attack or a stroke, the nearest hospital isn't always the right one. A small hospital without a cath lab or CT scan just wastes time before referring you somewhere else.

So IlaajSaathi does two things: in an emergency it sends you to the nearest hospital that can actually treat it, and the rest of the time it finds you the most affordable safe path.

## How it's different from what already exists

I looked at what people currently use and none of them do this job end to end:

| What people use now | What it's good for | What it doesn't do |
|---|---|---|
| Google Maps "hospital near me" | Finding the closest hospitals | Doesn't know which ones can handle a heart attack or stroke, or which are government |
| Practo / Apollo 24\|7 type apps | Booking doctors and tests | Mostly private hospitals. Their business is selling consultations, not saving you money |
| PM-JAY / Ayushman portals | Checking eligibility, listing empanelled hospitals | Only useful if you know the scheme exists and think you qualify |
| eSanjeevani | Free video consult | Doesn't help with hospitals, costs or what to do next |
| Jan Aushadhi Sugam | Finding generic medicine stores | You need to know which generic matches your medicine |
| 108 | Ambulance | Doesn't tell the family where to go or what it'll cost afterwards |

What IlaajSaathi does differently:

1. **Routes by facility, not just distance.** It works out from the symptoms what the patient needs (cath lab for a heart attack, CT and stroke care for a stroke, trauma centre after an accident) and points to the nearest hospital that has it.
2. **Doesn't stop at "go to emergency".** After routing, it still builds the follow-up plan: Ayushman check, government hospitals, cost comparison and a summary to hand to the doctor.
3. **Saving money is the actual goal.** It looks for the government option, the scheme that pays and the generic medicine first. It has no reason to push private hospitals.
4. **One conversation instead of six apps.** You say "papa ko blockage hai, angioplasty ke 3 lakh bataye, Delhi, budget 30 hazaar" and it checks safety, eligibility, hospitals, costs and medicines by itself.
5. **Made for people who don't know the system.** Hindi voice input, no forms, and you don't need to have heard of eSanjeevani or Ayushman Vay Vandana.
6. **Free to run anywhere.** Maps use OpenStreetMap by default, so there's no per-user cost. Google Maps can be switched on for live traffic.

## What the agent actually does

The flow is: understand → safety check → plan → use tools → act → reply.

1. **Understands the message.** Pulls out the problem (heart, knee, kidney, eye...), whether a procedure was advised, any cost the hospital quoted, the budget, age, city, and current medicines. Works with Hindi, Hinglish and English.
2. **Safety check first.** This part is plain code, not the LLM, so it can't be skipped. Chest pain with sweating, face drooping, losing bladder control, a bad accident, and so on all count as emergencies.
3. **If it's an emergency:** finds the nearest hospital with the right facility, shows travel time, a Call 108 button, directions and a map, and reminds the family that hospitals have to stabilise emergencies before talking about money. Then it continues with the affordable follow-up plan.
4. **If it's not:** it asks once for anything missing (location or budget), then plans which tools to run.
5. **Tools it uses:**
   - free consult options (eSanjeevani, government OPD, wellness centres)
   - Ayushman Bharat eligibility estimate
   - nearest government hospitals with the right department, with travel time
   - government vs private cost comparison for the likely treatment
   - generic medicine matches from Jan Aushadhi
   - questions to ask before agreeing to a procedure
6. **Takes action:** creates a one-page PDF summary for the doctor and a calendar reminder to book the free consult.
7. **Replies** in the same language you wrote in. The web page also shows every step the agent took, so you can see what it did and why.

It never diagnoses, never prescribes and never tells anyone to stop a medicine.

## Tech stack

- Python. The server is just the standard library, the only package is `reportlab` for the PDF
- OpenStreetMap: Nominatim (location search), Overpass (nearby hospitals), OSRM (road travel time). All free, no key
- Google Maps Platform (optional): Geocoding, Places API (New), Routes API
- Gemini (through its OpenAI-compatible API) for understanding messy Hindi/English, planning and writing replies. Groq, OpenAI or Claude also work. Optional, everything has a rule-based fallback
- Browser APIs for voice input (Hindi/English) and location
- Docker, deployed on Render



## Project structure

```
app/
  agent.py         the main agent loop: understand, safety check, plan, run tools, reply
  tools.py         all the tools (safety check, emergency routing, schemes, hospitals, costs, generics...)
  geo.py           maps: OpenStreetMap by default, Google if a key is set, offline fallback
  llm.py           optional LLM calls
  pdf_summary.py   the doctor summary PDF
  server.py        web server and API
  static/          the web page
  data/            hospital list, procedure costs, generic medicine prices
tests/             16 tests
docs/              architecture diagram, demo script, pitch notes
agent.yaml         agent manifest
Dockerfile
```

## Limitations

Things I know aren't perfect yet:

- **Costs are estimates.** The government vs private ranges and medicine prices are rough planning numbers, not official PM-JAY package rates. The app says so wherever it shows them.
- **Eligibility is a guess.** The Ayushman check is an estimate based on what you tell it. It always points you to beneficiary.nha.gov.in or 14555 for the real answer.
- **Facility data is limited.** I made a list of government hospitals with known facilities for Delhi, Lucknow, Patna, Mumbai, Bengaluru and Jaipur. Outside those cities it uses OpenStreetMap, which usually doesn't record things like cath labs, so in an emergency it tells people to call 108 first and to call the hospital ahead instead of guessing.
- **Free map servers can be slow** at busy times.
- **Prescription photo reading** only works when an LLM key is set.

## What I'd add next

- Official PM-JAY hospital list and package rates for every district
- Live bed and facility availability from state health systems or 108
- Booking the OPD slot or ambulance directly instead of just pointing to it
- A WhatsApp voice version, since that's what most people already use
- More languages

## Disclaimer

IlaajSaathi is a hackathon prototype. It helps people find affordable care, it is not a doctor. In an emergency, call 108.
