"""Lot number format tests (PR.015 7.4). Pure functions only - no database, no site needed:

	cd apps/medic_customizations && ../../env/bin/python -m unittest medic_customizations.medic_customizations.traceability.test_lot_naming
"""

import unittest
from datetime import date
from unittest.mock import patch

from medic_customizations.medic_customizations.traceability import lot_naming
from medic_customizations.medic_customizations.traceability.lot_naming import build_lot, lot_suffix, year_week


class TestLotNaming(unittest.TestCase):
	def test_pr015_example(self):
		# PR.015 7.8: pouch sealed in 2026 week 01, first run, MDI200095 -> 260100200095
		self.assertEqual(build_lot("MDI200095", date(2026, 1, 2), 0), "260100200095")

	def test_finished_product_example(self):
		# PR.015 7.4: 25 33 00 600222
		self.assertEqual(build_lot("PDI600222", date(2025, 8, 13), 0), "253300600222")

	def test_bc_is_two_digits(self):
		self.assertEqual(build_lot("PDI600222", date(2025, 8, 13), 1), "253301600222")
		self.assertEqual(build_lot("PDI600222", date(2025, 8, 13), 12), "253312600222")

	def test_irregular_codes(self):
		cases = {
			"MDI200005B": "200005B",
			"MDI2000022": "2000022",
			"PDI600111-1": "6001111",
			"PDI600116-1": "6001161",
			"387300-361": "387300361",
			"800330": "800330",
			"MD200178": "200178",
			"MPR100010": "100010",
			" pdi600222 ": "600222",
		}
		for code, suffix in cases.items():
			with self.subTest(code=code):
				self.assertEqual(lot_suffix(code), suffix)

	def test_iso_week_year_edges(self):
		self.assertEqual(year_week(date(2026, 1, 1)), "2601")  # Thursday -> ISO week 1 of 2026
		self.assertEqual(year_week(date(2027, 1, 1)), "2653")  # Friday -> ISO week 53 of 2026
		self.assertEqual(year_week(date(2024, 12, 30)), "2501")  # Monday -> ISO week 1 of 2025

	def test_calendar_week_mode(self):
		with patch.dict(lot_naming.LOT_NAMING, {"week": "calendar"}):
			self.assertEqual(year_week(date(2027, 1, 1)), "2700")
			self.assertEqual(year_week(date(2024, 12, 30)), "2453")


if __name__ == "__main__":
	unittest.main()
