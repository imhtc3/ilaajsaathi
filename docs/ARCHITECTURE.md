# Architecture

```mermaid
flowchart TD
    U[Patient or family: voice / text in Hindi or English<br/>+ device location + optional prescription photo] --> UN[Understand<br/>rules + optional LLM extraction]
    UN --> SG{Reason: safety gate<br/>red_flag_check}
    SG -- emergency --> RE[route_emergency<br/>facility needed: cath lab / stroke / trauma / neuro<br/>Google Places + Routes, OSM, curated list]
    RE --> EA[Act: Go to hospital X, N min<br/>Call 108, directions, map, nearest govt option]
    EA --> FU[Affordable follow-up:<br/>Ayushman check, govt hospitals, costs, doctor summary PDF]
    SG -- not urgent --> MI{Location and budget known?}
    MI -- no --> Q[Ask one follow-up question]
    Q --> U
    MI -- yes --> PL[Plan: choose tools + reasons<br/>LLM planner or rule planner<br/>guardrails enforce mandatory steps]
    PL --> T1[teleconsult_options]
    PL --> T2[check_pmjay_eligibility]
    PL --> T3[find_hospitals<br/>nearest govt + travel time]
    PL --> T4[estimate_costs]
    PL --> T5[find_generics]
    PL --> T6[second_opinion_questions]
    T1 & T2 & T3 & T4 & T5 & T6 --> AC[Act: doctor summary PDF + calendar reminder]
    AC --> D[Deliver: reply in user's language<br/>plan + money saved + step trace]
    FU --> D
```

## Design choices
- **Safety is code, not prompt.** Red-flag detection is deterministic and always runs first. Each emergency maps to the facility it needs, so the patient is sent somewhere that can actually treat them.
- **Route, then keep helping.** Emergencies never wait for follow-up questions, and never end the conversation: the affordable follow-up plan is built underneath.
- **Maps with graceful fallback.** Google Maps Platform (Geocoding, Places, Routes) when a key is set; free OpenStreetMap otherwise; a curated government-hospital list with coordinates when offline. Directions links work with no key.
- **LLM optional.** Every step has a rule-based path, so the demo and API never fail on an outage. With a key, the LLM handles messy language, plans tool order, reads prescription photos and writes natural replies.
- **Guardrails over the planner.** Unknown tool names from the LLM are dropped; the safety check, emergency routing, summary and (non-urgent) reminder are always enforced.
- **Zero-infra.** Python standard library server + one dependency (reportlab).
