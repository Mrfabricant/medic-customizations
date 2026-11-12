"""Batch (lot) numbers per PR.015 Rev09 section 7.4: YY WW BC + the item's article digits.

	260100200095 = 2026, ISO week 01, BC 00 (first run that week), MDI200095

Wired as Batch.before_insert (hooks.py). ERPNext names a Batch after its batch_id, so the lot only has
to be put there before insert; a Batch ID typed by hand (e.g. a supplier lot) is always kept as is.
It does nothing until an item has "Has Batch No" ticked.

Why not a native naming series: Frappe's series counter is keyed on the text before the #-part (so
one counter would be shared by every item), starts at 01 not 00, and uses today's date instead of
the production week.

Everything that is a policy choice sits in LOT_NAMING below.
"""

import re
from datetime import date

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

LOT_NAMING = {
	# "iso": ISO 8601 week and ISO week-year of the batch's manufacturing date (2027-01-01 -> 26 53).
	# "calendar": calendar year + ISO week number, clamped like Frappe's WW (2027-01-01 -> 27 00).
	"week": "iso",
	# "item_week": BC counts this item's runs in that week (00, 01, ...). "week": one counter per week
	# shared by all items.
	"bc_scope": "item_week",
	"bc_start": 0,
	"bc_digits": 2,
}

# Which date a lot belongs to when the Batch has no manufacturing date yet: the posting date of the
# document that creates it (or a Work Order's planned start), else today.
REFERENCE_DATE_FIELDS = {
	"Stock Entry": "posting_date",
	"Purchase Receipt": "posting_date",
	"Purchase Invoice": "posting_date",
	"Subcontracting Receipt": "posting_date",
	"Work Order": "planned_start_date",
}


def lot_suffix(item_code: str) -> str:
	"""Article digits of an item code: leading letters and any punctuation dropped, variant letters kept.

	PDI600222 -> 600222, MDI200095 -> 200095, MDI200005B -> 200005B, PDI600111-1 -> 6001111,
	387300-361 -> 387300361, MD200178 -> 200178, MPR100010 -> 100010.
	"""
	suffix = re.sub(r"[^0-9A-Z]", "", re.sub(r"^[A-Z]+", "", (item_code or "").strip().upper()))
	if not suffix:
		frappe.throw(_("Item {0}: no article digits to build a lot number from.").format(frappe.bold(item_code)))
	return suffix


def year_week(d) -> str:
	d = getdate(d)
	iso_year, iso_week, _weekday = d.isocalendar()
	if LOT_NAMING["week"] == "iso":
		return f"{iso_year % 100:02d}{iso_week:02d}"
	# calendar year with Frappe's clamping at the year edges
	week = iso_week
	if d.month == 1 and week >= 52:
		week = 0
	elif d.month == 12 and week <= 1:
		week = 53
	return f"{d.year % 100:02d}{week:02d}"


def build_lot(item_code: str, manufacturing_date, bc: int) -> str:
	digits = LOT_NAMING["bc_digits"]
	if bc < 0 or bc >= 10**digits:
		frappe.throw(_("Batch code {0} does not fit in {1} digits.").format(bc, digits))
	return f"{year_week(manufacturing_date)}{bc:0{digits}d}{lot_suffix(item_code)}"


def next_bc(item_code: str, manufacturing_date) -> int:
	"""The next free BC: one higher than the highest already used in that week (gaps are not reused)."""
	prefix, digits = year_week(manufacturing_date), LOT_NAMING["bc_digits"]
	if LOT_NAMING["bc_scope"] == "item_week":
		pattern = re.compile(rf"^{prefix}(\d{{{digits}}}){re.escape(lot_suffix(item_code))}$")
		names = frappe.get_all("Batch", filters={"item": item_code, "name": ["like", f"{prefix}%"]}, pluck="name")
	else:
		pattern = re.compile(rf"^{prefix}(\d{{{digits}}})")
		names = frappe.get_all("Batch", filters={"name": ["like", f"{prefix}%"]}, pluck="name")
	used = [int(m.group(1)) for m in map(pattern.match, names) if m]
	return max(used) + 1 if used else LOT_NAMING["bc_start"]


def _manufacturing_date(doc) -> date:
	if doc.get("manufacturing_date"):
		return getdate(doc.manufacturing_date)
	field = REFERENCE_DATE_FIELDS.get(doc.get("reference_doctype"))
	if field and doc.get("reference_name"):
		value = frappe.db.get_value(doc.reference_doctype, doc.reference_name, field)
		if value:
			return getdate(value)
	return getdate(nowdate())


def set_batch_lot(doc, method=None):
	"""Batch.before_insert: give a new batch without a Batch ID its PR.015 lot number."""
	if doc.get("batch_id") or not doc.get("item"):
		return

	manufacturing_date = _manufacturing_date(doc)
	lot = build_lot(doc.item, manufacturing_date, next_bc(doc.item, manufacturing_date))
	holder = frappe.db.get_value("Batch", lot, "item")
	if holder:
		# Two article numbers can share their digits (e.g. PDI800111 / MDI800111). Never change the BC
		# silently - the BC must keep meaning "nth run of this item this week".
		frappe.throw(
			_(
				"Lot number {0} for item {1} is already used by item {2}: both article numbers end in the same "
				"digits. Enter the Batch ID by hand for this batch."
			).format(frappe.bold(lot), frappe.bold(doc.item), frappe.bold(holder)),
			title=_("Lot number already in use"),
		)

	doc.manufacturing_date = manufacturing_date
	doc.batch_id = lot
