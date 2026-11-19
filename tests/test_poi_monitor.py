import unittest
from poi_monitor import PriceZone, detect_poi_mitigation, ltf_watch_status
from smc_engine import Candle, StructureEvent


class PoiMonitorTests(unittest.TestCase):
    def setUp(self):
        self.zone = PriceZone("eurusd-m15-ob-1", "EURUSD", "bearish", 1.0800, 1.0810, "M15", 1800000000)

    def test_closed_candle_overlap_triggers_mitigation(self):
        result = detect_poi_mitigation(self.zone, Candle(1800000060, 1.0820, 1.0825, 1.0805, 1.0810))
        self.assertEqual(result["event"], "POI_MITIGATED")
        self.assertEqual(result["zone_id"], self.zone.zone_id)

    def test_live_candle_does_not_trigger(self):
        self.assertIsNone(detect_poi_mitigation(self.zone, Candle(1800000060, 1.0820, 1.0825, 1.0805, 1.0810, closed=False)))

    def test_pre_zone_candle_does_not_trigger(self):
        self.assertIsNone(detect_poi_mitigation(self.zone, Candle(1799999999, 1.0820, 1.0825, 1.0805, 1.0810)))

    def test_bad_zone_rejected(self):
        with self.assertRaises(ValueError):
            detect_poi_mitigation(PriceZone("x", "XAUUSD", "bullish", 1, 2, "M15", 1), Candle(2, 1.2, 1.3, 1.1, 1.2))

    def test_watch_waits_for_m1_mss(self):
        self.assertEqual(ltf_watch_status("bullish", [], [], [])["status"], "WATCHING")

    def test_watch_requires_m3_and_m5(self):
        m1 = StructureEvent("M1", "bullish", "MSS", 1.1, 100, 90, True, 1.2, 1.3, .8, True, .4, True, ())
        m3 = StructureEvent("M3", "bullish", "BOS", 1.1, 100, 90, True, 1.2, 1.3, .8, False, .4, True, ())
        m5 = StructureEvent("M5", "bullish", "BOS", 1.1, 100, 90, True, 1.2, 1.3, .8, False, .4, True, ())
        self.assertEqual(ltf_watch_status("bullish", [m1], [m3], [m5])["status"], "LTF_CONFIRMATION_CANDIDATE")
        self.assertEqual(ltf_watch_status("bullish", [m1], [m3], [])["reason"], "waiting_for_m5_support")


if __name__ == "__main__":
    unittest.main()
