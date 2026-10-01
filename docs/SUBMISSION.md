# Submission checklist and form answers

## Checklist
- [ ] Push to GitHub (public repo)
- [ ] Deploy to Render/Railway (Docker) and test `POST /invoke`
- [ ] If using YAML method: align `agent.yaml` field names with the aiKart Agent Manifest Guide
- [ ] Record the 2–3 min demo video (docs/DEMO_SCRIPT.md)
- [ ] Build the 5-slide deck (docs/PITCH_DECK.md)
- [ ] Submit via your chosen method once the window opens (8:00 PM)
- [ ] Fill the official Google Form

## Draft form answers
- **Project name:** IlaajSaathi
- **Domain:** HealthTech
- **Problem statement:** Families told they need costly treatment (angioplasty, knee replacement, kidney surgery) pay private prices or delay care because they do not know about free consults, Ayushman Bharat cover or nearby government hospitals; in emergencies they lose time reaching hospitals without the right facility.
- **Solution overview:** A Hindi/English voice-and-text agent that routes emergencies to the nearest hospital with the needed facility (cath lab, stroke care, trauma) using Google Maps, with 108 and directions, and otherwise finds free consults, Ayushman Bharat eligibility, nearest government hospitals, government vs private costs and generic medicines, then creates a doctor summary PDF and reminder.
- **Agent workflow:** Understand → safety gate → emergency routing, or ask for missing info → plan tools (LLM planner + guardrails) → run tools → act (PDF, reminder) → deliver reply and plan with a visible trace.
- **Tech stack:** Python (standard-library HTTP server), reportlab, Google Maps Platform (Geocoding, Places API New, Routes API), OpenStreetMap fallback, optional Claude / OpenAI-compatible LLM, Web Speech + Geolocation APIs, Docker, Render.
