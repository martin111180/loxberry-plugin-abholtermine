"""Tests für Parser (umweltprofis.py) und Datumslogik (termine.py).

Die Fixtures sind Ausschnitte der echten Website (Linz-Land, abgerufen am 15.11.2026).
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "plugin" / "bin"))

import termine  # noqa: E402
import umweltprofis  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def calendar():
    return umweltprofis.parse_calendar((FIXTURES / "kalender.html").read_text(encoding="utf-8"))


class ParserTest(unittest.TestCase):
    def test_entries(self):
        data = calendar()
        self.assertEqual(len(data["entries"]), 11)
        first = data["entries"][0]
        self.assertEqual(first["date"], "2026-11-17")
        self.assertEqual(first["type"], "Restabfall")
        self.assertEqual(first["interval"], "4-wöchentlich")
        self.assertEqual(first["interval_id"], "o410969")

    def test_types_with_intervals(self):
        types = {t["name"]: t for t in calendar()["types"]}
        self.assertEqual(sorted(types), ["Altpapier", "Bioabfall", "Gelber Sack", "Restabfall"])
        self.assertEqual([i["name"] for i in types["Restabfall"]["intervals"]], ["2-wöchentlich", "4-wöchentlich"])
        self.assertEqual(types["Bioabfall"]["intervals"], [])

    def test_form(self):
        action, fields = umweltprofis.parse_form((FIXTURES / "formular.html").read_text(encoding="utf-8"))
        self.assertIn("ajaxChooseLocation", action)
        self.assertNotIn("&amp;", action)
        names = [n for n, _ in fields]
        self.assertIn("tx_ecxumweltprofis_pi2[__trustedProperties]", names)
        trusted = dict(fields)["tx_ecxumweltprofis_pi2[__trustedProperties]"]
        self.assertTrue(trusted.startswith('{"location":'))


class LogicTest(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(termine.slug("Gelber Sack"), "gelber_sack")
        self.assertEqual(termine.slug("Bioabfall"), "bioabfall")
        self.assertEqual(termine.slug("Altstoffe/Glas (bunt)"), "altstoffe_glas_bunt")
        self.assertEqual(termine.slug("Größe ÄÖÜ"), "groesse_aeoeue")

    def test_default_interval_like_website(self):
        sel = termine.select_entries(calendar(), {})
        rest = [e for e in sel if e["type"] == "Restabfall"]
        self.assertTrue(rest)
        self.assertTrue(all(e["interval"] == "2-wöchentlich" for e in rest))

    def test_filters(self):
        data = calendar()
        four = termine.select_entries(data, {"Restabfall": "4-wöchentlich"})
        self.assertTrue(all(e["interval"] == "4-wöchentlich" for e in four if e["type"] == "Restabfall"))
        none = termine.select_entries(data, {"Restabfall": termine.FILTER_NEVER})
        self.assertFalse([e for e in none if e["type"] == "Restabfall"])
        both = termine.select_entries(data, {"Restabfall": termine.FILTER_ALL})
        # 17.11. kommt in beiden Intervallen vor -> nur einmal
        self.assertEqual(len([e for e in both if e["date"] == "2026-11-17"]), 1)

    def test_day_before_reminder(self):
        data = calendar()
        afternoon = termine.compute(data, {}, 14, dt.datetime(2026, 11, 16, 12, 0), "18:00")["values"]
        self.assertEqual(afternoon["morgen"], "1")
        self.assertEqual(afternoon["morgen_text"], "Restabfall")
        self.assertEqual(afternoon["erinnerung"], "0")
        evening = termine.compute(data, {}, 14, dt.datetime(2026, 11, 16, 18, 0), "18:00")["values"]
        self.assertEqual(evening["erinnerung"], "1")
        self.assertEqual(evening["erinnerung_text"], "Morgen wird abgeholt: Restabfall")
        pickup_day = termine.compute(data, {}, 14, dt.datetime(2026, 11, 17, 6, 0), "18:00")["values"]
        self.assertEqual(pickup_day["erinnerung"], "0")
        self.assertEqual(pickup_day["heute"], "1")
        self.assertEqual(pickup_day["restabfall/tage"], "0")

    def test_values(self):
        res = termine.compute(calendar(), {}, 14, dt.datetime(2026, 11, 15, 10, 0))
        v = res["values"]
        self.assertEqual(v["naechste_tage"], "2")
        self.assertEqual(v["naechste_text"], "Restabfall übermorgen (Di 17.11.)")
        self.assertEqual(v["naechste_datum"], "Di, 17.11.2026")
        self.assertEqual(int(v["naechste_datum_lox"]), (dt.date(2026, 11, 17) - dt.date(2009, 1, 1)).days * 86400)
        self.assertEqual(v["gelber_sack/tage"], "5")
        self.assertEqual(v["gelber_sack/text"], "in 5 Tagen (Fr 20.11.)")
        # Altpapier hat im Zeitraum keinen Termin
        self.assertEqual(v["altpapier/tage"], "-1")
        self.assertEqual(v["altpapier/text"], "kein Termin")
        # Bis 29.11. (14 Tage): 17.11. Rest, 20.11. Gelb, 25.11. Bio
        self.assertEqual(v["anzahl"], "3")
        self.assertEqual(v["liste"], "Di 17.11. Restabfall · Fr 20.11. Gelber Sack · Mi 25.11. Bioabfall")
        self.assertEqual(v["heute_text"], "-")
        # keine leeren Werte (leere retained Nachricht löscht ein Topic)
        self.assertTrue(all(val != "" for val in v.values()))

    def test_hidden_type_has_no_topics(self):
        v = termine.compute(calendar(), {"Altpapier": "-"}, 14, dt.datetime(2026, 11, 15))["values"]
        self.assertNotIn("altpapier/tage", v)

    def test_no_entries(self):
        v = termine.compute({"entries": [], "types": []}, {}, 7, dt.datetime(2026, 11, 15))["values"]
        self.assertEqual(v["naechste_tage"], "-1")
        self.assertEqual(v["liste"], "-")
        self.assertEqual(v["morgen"], "0")


if __name__ == "__main__":
    unittest.main()
