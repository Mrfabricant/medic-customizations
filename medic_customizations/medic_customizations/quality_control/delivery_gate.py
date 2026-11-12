import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import assert_inspected, row_entries


def validate_delivery_note_qc_gate(doc, method=None):
	# a return brings stock back in - there is nothing to release, so no final inspection applies
	if doc.get("is_return"):
		return

	entries = []
	for row in doc.items:
		if frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			entries += row_entries(row, row.stock_qty, _("cannot be delivered without a passed final inspection"))
	assert_inspected(doc, entries, inspection_type="Outgoing")
