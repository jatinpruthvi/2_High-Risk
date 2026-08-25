import unittest
from datetime import date, datetime, timezone

from institutional_options.candidates import CandidateFactory, CandidateFactoryContext
from institutional_options.config import SystemConfig
from institutional_options.fyers_parser import FyersOptionChainParser
from institutional_options.models import CalibrationStatus


class PartialFyersChainTests(unittest.TestCase):
    def test_missing_atm_leg_does_not_abort_cycle_candidate_build(self):
        payload = {
            "data": {
                "optionsChain": [
                    {"option_type": "", "strike_price": -1, "ltp": 100.0},
                    {"option_type": "PE", "strike_price": 100.0, "ltp": 10.0, "bid": 9.9, "ask": 10.1, "fyToken": "pe100"},
                    {"option_type": "CE", "strike_price": 101.0, "ltp": 9.0, "bid": 8.9, "ask": 9.1, "fyToken": "ce101"},
                ]
            }
        }
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime.now(timezone.utc))
        cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        ctx = CandidateFactoryContext(
            100.0, 100.0, 80.0, 80.0, 80.0, 10.0, 100.0, 100.0, 80.0, 10.0,
            CalibrationStatus.UNVALIDATED, CalibrationStatus.UNVALIDATED,
        )
        candidates = CandidateFactory(cfg).candidates_from_chain(chain, date(2026, 8, 25), 75, 0.05, ctx)
        self.assertEqual({(c.instrument.strike, c.side.value) for c in candidates}, {(100.0, "PE"), (101.0, "CE")})

    def test_missing_one_leg_skips_only_that_leg(self):
        payload = {
            "data": {
                "optionsChain": [
                    {"option_type": "", "strike_price": -1, "ltp": 100.0},
                    {"option_type": "CE", "strike_price": 100.0, "ltp": 10.0, "bid": 9.9, "ask": 10.1, "fyToken": "ce100"},
                    {"option_type": "PE", "strike_price": 100.0, "ltp": 10.0, "bid": 9.9, "ask": 10.1, "fyToken": "pe100"},
                    {"option_type": "CE", "strike_price": 101.0, "ltp": 9.0, "bid": 8.9, "ask": 9.1, "fyToken": "ce101"},
                ]
            }
        }
        chain = FyersOptionChainParser.parse(payload, "NIFTY", "2026-08-25", datetime.now(timezone.utc))
        cfg = SystemConfig.from_file("uploads/PARAMETERS.json")
        ctx = CandidateFactoryContext(
            100.0, 100.0, 80.0, 80.0, 80.0, 10.0, 100.0, 100.0, 80.0, 10.0,
            CalibrationStatus.UNVALIDATED, CalibrationStatus.UNVALIDATED,
        )
        candidates = CandidateFactory(cfg).candidates_from_chain(chain, date(2026, 8, 25), 75, 0.05, ctx)
        self.assertEqual(len(candidates), 3)
        self.assertEqual({(c.instrument.strike, c.side.value) for c in candidates}, {(100.0, "CE"), (100.0, "PE"), (101.0, "CE")})


if __name__ == "__main__":
    unittest.main()
