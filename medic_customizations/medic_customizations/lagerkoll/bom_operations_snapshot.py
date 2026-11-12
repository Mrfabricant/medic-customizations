"""Read-only snapshot of BOM Operations state, for before/after verification around
bom_operations_attach.py. Makes NO changes - safe to run any number of times, including
directly against a live production site, with no backup required for this script itself.

Run with:

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_operations_snapshot.run

Reuses classify()/_sterilization_items() from bom_operations_attach.py, so this reports exactly
the categories and BOM set that script itself acts on - there is no separate classification logic
to drift out of sync. Run this once BEFORE bom_operations_attach.py and once AFTER; the two
printed summaries are what should be compared.
"""

import frappe

from medic_customizations.medic_customizations.lagerkoll.bom_operations_attach import (
	classify,
	_sterilization_items,
)


def run():
	sterilization = _sterilization_items()
	categories = {}
	with_ops, without_ops = 0, 0
	total_operation_rows = 0
	boms_with_ops = []

	for b in frappe.get_all(
		"BOM",
		filters={"docstatus": ["!=", 2], "is_active": 1},
		fields=["name", "item", "with_operations"],
		order_by="name",
	):
		item_group = frappe.db.get_value("Item", b.item, "item_group")
		category, operations = classify(b.item, item_group, sterilization)
		categories[category] = categories.get(category, 0) + 1

		if not operations:
			# sterilization / needs_client_input / unclassified: never expected to carry operations
			continue

		op_count = frappe.db.count("BOM Operation", filters={"parent": b.name})
		total_operation_rows += op_count
		if b.with_operations and op_count:
			with_ops += 1
			boms_with_ops.append(b.name)
		else:
			without_ops += 1

	summary = {
		"categories": categories,
		"expected_to_have_operations": with_ops + without_ops,
		"already_have_operations": with_ops,
		"still_missing_operations": without_ops,
		"total_operation_rows_on_expected_boms": total_operation_rows,
	}
	print(summary)
	return {"summary": summary, "boms_with_operations": sorted(boms_with_ops)}
