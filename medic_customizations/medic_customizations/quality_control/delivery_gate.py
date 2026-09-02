import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.warehouse_gate import (
	has_passed_quality_inspection,
)


def validate_delivery_note_qc_gate(doc, method=None):
	for row in doc.items:
		if not has_passed_quality_inspection("Delivery Note", doc.name, row.item_code, row.get("batch_no")):
			frappe.throw(
				_(
					"Row #{0}: Item {1} cannot be delivered without a passed final Quality Inspection referencing this Delivery Note."
				).format(row.idx, frappe.bold(row.item_code))
			)
