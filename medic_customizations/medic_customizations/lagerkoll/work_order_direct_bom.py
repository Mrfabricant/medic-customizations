"""One-off: new Work Orders use the item's direct (single-level) BOM by default.

ERPNext ships Work Order "Use Multi-Level BOM" with default 1. A Work Order for a set then lists the
raw materials of the pump and the dressings instead of PDI600100 / PDI6002xx themselves, and pulls
in every sub-assembly's operations (10 instead of the set's 3 packaging steps). Here every stage is
its own Work Order (or, for sterilization, a Subcontracting Order), so the direct BOM is right.

How: a Property Setter "default = 0" on Work Order.use_multi_level_bom. That is the switch ERPNext
itself reads - BOM.onload uses exactly this Property Setter for its "Create Work Order" dialog;
Manufacturing Settings has no setting for it. It changes:
- a new Work Order (form, Sales Order > Work Order, BOM > Create Work Order): box unticked;
- NOT existing Work Orders (left as they are, listed in the output);
- NOT Production Plans: they set the flag per row ("Include Exploded Items" on the plan item), and
  once "Get Sub Assembly Items" was used every Work Order they make is single-level anyway.
A user can still tick the box on a single Work Order. To revert: Customize Form > Work Order >
Use Multi-Level BOM > Default.

A one-off script rather than an after_migrate step on purpose: if the client later changes the
default in Customize Form, a migrate must not silently put it back.

NOT wired into hooks.py or patches.txt. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.work_order_direct_bom.run

for a DRY RUN (computed, then rolled back), and pass --kwargs "{'dry_run': False}" to apply. Already in
place -> nothing changes, so it is safe to run twice.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MARKER = "Work Order direct BOM default"
DOCTYPE, FIELD, PROPERTY, VALUE = "Work Order", "use_multi_level_bom", "default", "0"


def apply() -> dict:
	"""The change itself, without commit or rollback (run() decides)."""
	existing = frappe.db.get_value(
		"Property Setter", {"doc_type": DOCTYPE, "field_name": FIELD, "property": PROPERTY}, ["name", "value"], as_dict=True
	)
	if existing and existing.value == VALUE:
		action = f"unchanged ({existing.name} already sets default {VALUE})"
	else:
		before = existing.value if existing else "1 (ERPNext standard)"
		ps = make_property_setter(
			DOCTYPE, FIELD, PROPERTY, VALUE, "Text", validate_fields_for_doctype=False, is_system_generated=False
		)
		ps.add_comment(
			"Info",
			f"{MARKER}: {DOCTYPE}.{FIELD} default {before} -> {VALUE}. New Work Orders use the direct BOM; "
			"sub-assemblies are made by their own Work Orders / Subcontracting Orders. Existing Work Orders unchanged.",
		)
		action = f"set: default {before} -> {VALUE} ({ps.name})"

	open_multi_level = frappe.get_all(
		"Work Order",
		filters={"use_multi_level_bom": 1, "docstatus": ["<", 2], "status": ["not in", ["Completed", "Closed", "Cancelled"]]},
		fields=["name", "production_item", "status"],
		order_by="name",
	)
	return {"action": action, "open_work_orders_still_multi_level": open_multi_level}


def run(dry_run: bool = True):
	result = apply()
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	frappe.clear_cache(doctype=DOCTYPE)  # drop cached meta either way (after rollback it rebuilds from the DB)
	print("  ", result["action"])
	for wo in result["open_work_orders_still_multi_level"]:
		print("   existing Work Order left as is (multi-level):", wo.name, wo.production_item, wo.status)
	print({"dry_run": dry_run})
	return result
