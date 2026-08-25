import unittest
from datetime import datetime

from institutional_options.models import Greeks, OptionType, Quote
from institutional_options.option_chain import OptionChainSnapshot, OptionLeg, OptionStrike
from institutional_options.surface_diagnostics import OptionSurfaceDiagnostics


class SurfaceDiagnosticsTests(unittest.TestCase):
    def leg(self, strike, side, iv):
        ts = datetime(2026, 8, 13, 10, 0)
        quote = Quote(99.5, 100.5, 1000, 1000, 100.0, ts, 5000, 5000)
        return OptionLeg(strike, side, f"{strike}-{side.value}", quote,
                         Greeks(delta=0.5 if side is OptionType.CE else -0.5),
                         iv, 1000, 900, 500, 400)

    def test_surface_diagnostics_calculate_atm_and_wings(self):
        strikes = (
            OptionStrike(24900, self.leg(24900, OptionType.CE, 18), self.leg(24900, OptionType.PE, 24)),
            OptionStrike(25000, self.leg(25000, OptionType.CE, 20), self.leg(25000, OptionType.PE, 22)),
            OptionStrike(25100, self.leg(25100, OptionType.CE, 23), self.leg(25100, OptionType.PE, 19)),
        )
        chain = OptionChainSnapshot("NIFTY", 25000, "2026-08-25", datetime(2026, 8, 13, 10, 0), strikes)
        result = OptionSurfaceDiagnostics.calculate(chain)
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.atm_iv, 21.0)
        self.assertAlmostEqual(result.call_put_iv_skew, -2.0)
        self.assertAlmostEqual(result.call_wing_iv, 23.0)
        self.assertAlmostEqual(result.put_wing_iv, 24.0)

    def test_empty_chain_is_invalid(self):
        chain = OptionChainSnapshot("NIFTY", 25000, "2026-08-25", datetime(2026, 8, 13, 10, 0), tuple())
        result = OptionSurfaceDiagnostics.calculate(chain)
        self.assertFalse(result.valid)
        self.assertIn("No strikes", result.reason)


if __name__ == "__main__":
    unittest.main()
