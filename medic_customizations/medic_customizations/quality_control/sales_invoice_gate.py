import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import assert_inspected, row_entries


def validate_sales_invoice_qc_gate(doc, method=None):
	# no stock moves without update_stock, and a return brings stock back in - nothing to release
	if not doc.update_stock or doc.get("is_return"):
		return

	entries = []
	for row in doc.items:
		if row.warehouse and frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			entries += row_entries(row, row.stock_qty, _("cannot be shipped without a passed final inspection"))
	assert_inspected(doc, entries, inspection_type="Outgoing")
