from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import assert_inspected


def validate_delivery_note_qc_gate(doc, method=None):
	entries = [
		{
			"idx": row.idx,
			"item_code": row.item_code,
			"batch_no": row.get("batch_no"),
			"qty": row.stock_qty,
			"context": _("cannot be delivered without a passed final inspection"),
		}
		for row in doc.items
	]
	assert_inspected(doc, entries, inspection_type="Outgoing")
