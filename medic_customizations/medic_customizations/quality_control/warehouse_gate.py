import frappe
from frappe import _


def get_qc_gated_warehouses() -> set[str]:
	return set(
		frappe.get_all(
			"Warehouse",
			filters={"custom_qc_required_on_exit": 1},
			pluck="name",
		)
	)


def has_passed_quality_inspection(reference_type: str, reference_name: str, item_code: str, batch_no: str | None) -> bool:
	filters = {
		"reference_type": reference_type,
		"reference_name": reference_name,
		"item_code": item_code,
		"status": "Accepted",
		"docstatus": 1,
	}
	if batch_no:
		filters["batch_no"] = batch_no

	return bool(frappe.db.exists("Quality Inspection", filters))


def validate_stock_entry_qc_gate(doc, method=None):
	gated_warehouses = get_qc_gated_warehouses()
	if not gated_warehouses:
		return

	for row in doc.items:
		if row.s_warehouse not in gated_warehouses:
			continue

		if not has_passed_quality_inspection("Stock Entry", doc.name, row.item_code, row.get("batch_no")):
			frappe.throw(
				_(
					"Row #{0}: Item {1} cannot leave warehouse {2} without a passed Quality Inspection referencing this Stock Entry."
				).format(row.idx, frappe.bold(row.item_code), frappe.bold(row.s_warehouse))
			)
