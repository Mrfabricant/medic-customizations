import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import assert_inspected


def validate_sales_invoice_qc_gate(doc, method=None):
	if not doc.update_stock:
		return

	entries = [
		{
			"idx": row.idx,
			"item_code": row.item_code,
			"batch_no": row.get("batch_no"),
			"qty": row.stock_qty,
			"context": _("cannot be shipped without a passed final inspection"),
		}
		for row in doc.items
		if row.warehouse and frappe.get_cached_value("Item", row.item_code, "is_stock_item")
	]
	assert_inspected(doc, entries, inspection_type="Outgoing")
