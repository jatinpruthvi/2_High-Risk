import tempfile
import unittest
from pathlib import Path

from institutional_options.mtil import MTILSchema, MTILWriter, MTILError


class MTILTests(unittest.TestCase):
    def test_schema_loads_and_writer_validates(self):
        schema = MTILSchema.from_csv("uploads/MTIL_SCHEMA.csv")
        with tempfile.TemporaryDirectory() as d:
            writer = MTILWriter(schema, Path(d) / "mtil.csv")
            record = {name: "X" for name in schema.required}
            writer.append(record)
            self.assertTrue((Path(d) / "mtil.csv").exists())

    def test_missing_required_raises(self):
        schema = MTILSchema.from_csv("uploads/MTIL_SCHEMA.csv")
        with tempfile.TemporaryDirectory() as d:
            writer = MTILWriter(schema, Path(d) / "mtil.csv")
            with self.assertRaises(MTILError):
                writer.append({})


if __name__ == "__main__":
    unittest.main()
