"""Run: python -m unittest discover tests   (no API keys or network needed)"""
import os
import tempfile
import unittest

os.environ.setdefault("ILAAJ_OUT_DIR", tempfile.mkdtemp())
os.environ["ILAAJ_USE_OSM"] = "0"
for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY"):
    os.environ.pop(k, None)

from app import agent, geo, tools  # noqa: E402

DELHI_GPS = (28.60, 77.22)


class TestEmergencyRouting(unittest.TestCase):
    def test_heart_attack_routes_to_cath_lab_and_keeps_affordable_plan(self):
        r = agent.handle("Severe chest pain right now with sweating and left arm pain", lat=DELHI_GPS[0], lng=DELHI_GPS[1])
        self.assertEqual(r["status"], "urgent")
        em = r["plan"]["route_emergency"]
        self.assertEqual(em["facility"], "cath_lab")
        self.assertIn("cath_lab", em["best"]["facilities"])
        self.assertIn(em["best"]["name"], r["reply"])
        self.assertIn("108", r["reply"])
        # does not stop at the emergency: affordable follow-up is still planned
        self.assertIn("find_hospitals", r["plan"])
        self.assertIn("check_pmjay_eligibility", r["plan"])
        self.assertNotIn("create_reminder", r["plan"])

    def test_stroke_without_location_asks_for_it_but_still_acts(self):
        r = agent.handle("my mother's face is drooping and her speech is slurred")
        self.assertEqual(r["status"], "urgent")
        self.assertEqual(r["need"], "location")
        self.assertEqual(r["plan"]["route_emergency"]["facility"], "stroke")
        self.assertIn("108", r["reply"])

    def test_emergency_follow_up_with_city_routes(self):
        r = agent.handle("Sudden weakness, cannot control urine")
        r = agent.handle("I live in Lucknow", r["session_id"])
        self.assertEqual(r["status"], "urgent")
        self.assertIn("neurosurgery", r["plan"]["route_emergency"]["best"]["facilities"])

    def test_chest_pain_on_walking_is_not_an_emergency(self):
        rf = tools.red_flag_check("chest pain while walking for 3 months")
        self.assertFalse(rf["urgent"])
        self.assertEqual(rf["red_flags"][0]["key"], "chest_exertion")

    def test_hindi_emergency(self):
        self.assertEqual(tools.red_flag_check("अचानक सीने में दर्द और पसीना")["facility_needed"], "cath_lab")
        self.assertEqual(tools.red_flag_check("मुंह टेढ़ा हो गया, लकवा जैसा")["facility_needed"], "stroke")


class TestAffordablePlan(unittest.TestCase):
    def test_heart_case_end_to_end(self):
        r = agent.handle("Chest pain while walking. Angiography showed blockage, private hospital quoted 3 lakh for "
                         "angioplasty. We can spend only 30000. Delhi. He takes Atorva and Clopilet.")
        self.assertEqual(r["status"], "plan_ready")
        p = r["plan"]
        self.assertEqual(r["profile"]["quoted_cost"], 300000)
        self.assertEqual(r["profile"]["budget"], 30000)
        self.assertIn("Angioplasty with stent", p["estimate_costs"]["saving_basis"])
        self.assertTrue(all(h["type"] == "Government" for h in p["find_hospitals"]["hospitals"]))
        self.assertTrue(p["find_hospitals"]["hospitals"][0]["directions"].startswith("https://www.google.com/maps/dir/"))
        self.assertEqual(len(p["find_generics"]["matches"]), 2)
        self.assertNotIn("cheap", r["reply"].lower())
        for f in (p["make_doctor_summary"]["file"], p["create_reminder"]["file"]):
            self.assertTrue(os.path.exists(os.path.join(tools.OUT_DIR, f)))

    def test_asks_for_location_then_budget(self):
        r = agent.handle("Doctor advised knee replacement")
        self.assertEqual((r["status"], r["need"]), ("need_info", "location"))
        r = agent.handle("Jaipur", r["session_id"])
        self.assertEqual((r["status"], r["need"]), ("need_info", "budget"))
        r = agent.handle("budget 1 lakh", r["session_id"])
        self.assertEqual(r["status"], "plan_ready")

    def test_gps_location_skips_city_question(self):
        r = agent.handle("Kidney stone, doctor says operation, budget 20k", lat=26.85, lng=80.95)
        self.assertEqual(r["status"], "plan_ready")
        self.assertIn("minutes", r["plan"]["find_hospitals"]["hospitals"][0])

    def test_hindi_knee(self):
        r = agent.handle("मेरे पिताजी 72 साल के हैं, घुटने खराब हैं। डॉक्टर ने घुटना बदलने का ऑपरेशन बोला, 4 लाख बताया। "
                         "हम पटना में हैं, 50000 रुपये तक खर्च कर सकते हैं।")
        self.assertEqual(r["status"], "plan_ready")
        self.assertEqual(r["profile"]["quoted_cost"], 400000)
        self.assertEqual(r["plan"]["check_pmjay_eligibility"]["status"], "likely")
        self.assertRegex(r["reply"], r"[\u0900-\u097F]")


class TestGeo(unittest.TestCase):
    def test_offline_geocode_and_estimate(self):
        g = geo.geocode("Patna")
        self.assertEqual(g["source"], "offline")
        t = geo.travel_times((g["lat"], g["lng"]), [(25.5590, 85.0545)])[0]
        self.assertGreater(t["minutes"], 0)

    def test_google_places_parsing(self):
        os.environ["GOOGLE_MAPS_API_KEY"] = "test"
        orig = geo._post
        geo._post = lambda url, body, headers: {"places": [{"displayName": {"text": "City Heart Hospital"},
                                                             "location": {"latitude": 28.6, "longitude": 77.2},
                                                             "nationalPhoneNumber": "011 1234", "googleMapsUri": "https://maps.google.com/?cid=9"}]}
        try:
            res = geo.google_places("hospital with cath lab", 28.6, 77.2)
            self.assertEqual(res[0]["name"], "City Heart Hospital")
            self.assertEqual(res[0]["source"], "google")
        finally:
            geo._post = orig
            os.environ.pop("GOOGLE_MAPS_API_KEY")


class TestExtraction(unittest.TestCase):
    def test_budget_and_quote(self):
        for text, b, q in [("budget 20000", 20000, None), ("can spend 2 lakh", 200000, None),
                           ("hospital ne 1.5 lakh bataya, hum 20k tak kharch kar sakte", 20000, 150000),
                           ("quoted 3 lakh for angioplasty, we can spend only 30000", 30000, 300000)]:
            p = agent._rules_extract(text)
            self.assertEqual((p.get("budget"), p.get("quoted_cost")), (b, q), text)

    def test_conditions_in_order(self):
        self.assertEqual(agent._rules_extract("kidney stone and knee pain")["conditions"], ["kidney", "knee"])
        self.assertNotIn("conditions", agent._rules_extract("I will come back tomorrow"))


if __name__ == "__main__":
    unittest.main()
