import unittest
from datetime import date

from institutional_options.mapping import InstrumentMaster, MasterRecord, InstrumentMappingError, round_to_tick
from institutional_options.models import OptionType


class MappingTests(unittest.TestCase):
    def setUp(self):
        self.master = InstrumentMaster([
            MasterRecord("NSE", "D", "101", "OPTIDX", "NIFTY", "NIFTY", "NIFTY 25000 CE", 75, date(2026, 6, 30), 25000.0, "CE", 0.05, 1800, "A"),
            MasterRecord("NSE", "D", "102", "FUTIDX", "NIFTY", "NIFTY", "NIFTY JUN FUT", 75, date(2026, 6, 30), 0.0, None, 0.05, 1800, "A"),
        ])

    def test_find_index_option(self):
        spec = self.master.find_index_option("NIFTY", date(2026, 6, 30), 25000.0, OptionType.CE)
        self.assertEqual(spec.security_id, "101")
        self.assertEqual(spec.lot_size, 75)
        self.assertEqual(spec.option_type, OptionType.CE)

    def test_missing_instrument_raises(self):
        with self.assertRaises(InstrumentMappingError):
            self.master.find_index_option("BANKNIFTY", date(2026, 6, 30), 55000.0, OptionType.CE)

    def test_round_to_tick(self):
        self.assertEqual(round_to_tick(100.026, 0.05), 100.05)


if __name__ == "__main__":
    unittest.main()
