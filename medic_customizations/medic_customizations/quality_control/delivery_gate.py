import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import assert_inspected


def validate_delivery_note_qc_gate(doc, method=None):
	# a return brings stock back in - there is nothing to release, so no final inspection applies
	if doc.get("is_return"):
		return

	entries = [
		{
			"idx": row.idx,
			"item_code": row.item_code,
			"batch_no": row.get("batch_no"),
			"qty": row.stock_qty,
			"context": _("cannot be delivered without a passed final inspection"),
		}
		for row in doc.items
		if frappe.get_cached_value("Item", row.item_code, "is_stock_item")
	]
	assert_inspected(doc, entries, inspection_type="Outgoing")
