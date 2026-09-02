import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.warehouse_gate import (
	has_passed_quality_inspection,
)


def validate_sales_invoice_qc_gate(doc, method=None):
	if not doc.update_stock:
		return

	for row in doc.items:
		if not row.warehouse or not frappe.get_cached_value("Item", row.item_code, "is_stock_item"):
			continue

		if not has_passed_quality_inspection("Sales Invoice", doc.name, row.item_code, row.get("batch_no")):
			frappe.throw(
				_(
					"Row #{0}: Item {1} cannot be shipped without a passed final Quality Inspection referencing this Sales Invoice."
				).format(row.idx, frappe.bold(row.item_code))
			)
