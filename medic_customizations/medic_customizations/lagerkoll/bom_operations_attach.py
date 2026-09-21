"""One-off attachment of Operations to the already-submitted BOMs.

Why a direct edit: BOM.with_operations is not an "allow on submit" field, so a normal doc.save() on a
submitted BOM fails with UpdateAfterSubmitError ("Not allowed to change With Operations after
submission from 0 to 1"). Cancel/amend would break the links from item default BOMs, Subcontracting
BOMs and parent BOMs, so, like the sterilization-ratio and quantity fixes, the change is written
directly: with_operations is set, the operation rows are inserted, and what depends on them is
recomputed with ERPNext's own routines (validate_operations fills the description and batch size,
calculate_op_cost the hour rate and cost).

NOT wired into hooks.py or patches.txt, on purpose: a manual, one-time data change. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_operations_attach.run

for a DRY RUN (everything is computed, then rolled back), and pass --kwargs "{'dry_run': False}" to
apply. Take a backup first. A BOM that already has operations, or that carries the audit-comment
MARKER, is skipped, so it is safe to run twice.

PLACEHOLDER TIMES: every operation gets DEFAULT_TIME_MINUTES (5). These are NOT real times. The real
operation times have to come from the client before the operations are used for scheduling or
costing. (All workstation hour rates are currently 0, so the placeholder costs nothing.)

The BOM -> Operation mapping mirrors attach_bom_operations.py in the bench folder (the chain BOMs
verified against the work instructions; the rest of the Finished Products get the generic
3-step packing sequence). Deliberately left alone, whatever their state:
- the 13 sterilization-subcontracted BOMs (sterilization is external: no internal operation),
- the 5 BOMs in NEEDS_CLIENT_INPUT (no instruction describes making them; the client has to say),
- any BOM that is neither chain-mapped nor a Finished Product (the two IFU-pack consumables).

Enabling operations changes how Work Orders behave: a Work Order on one of these BOMs now creates
Job Cards per operation. No Work Orders or Job Cards exist yet.
"""

import frappe
from frappe.utils import flt, now

from medic_customizations.medic_customizations.setup import CHECKPOINT_ITEMS, STERILIZED_TEMPLATES

MARKER = "BOM operations attach"
DEFAULT_TIME_MINUTES = 5  # PLACEHOLDER - real operation times must come from the client

# item_code -> the single Operation that makes it (mirrors attach_bom_operations.py)
CHAIN_OPERATIONS = {
	"MDI100032": "Pump Soldering",
	"MDI100033": "Battery Connector Soldering",
	"MDI100039": "Mechanical Assembly",
	"MDI100045": "Install PCBA",
	"MDI100040": "Programming and Testing",
	"MDI100067": "Programming and Testing",
	"MDI100041": "Install Front Enclosure",
	"MDI100068": "Install Front Enclosure",
	"MDI100043": "Labeling and Back Cover",
	"MDI100078": "Labeling and Back Cover",
	"MDI100044": "Device Packing in Container",
	"MDI100079": "Device Packing in Container",
	"PDI600100": "Container Sealing",
	"PDI600400": "Container Sealing",
	"MDI200079": "Cut TPU Film",
	"MDI200080": "Cut TPU Film",
	"MDI200123": "Cut 3D Mesh",
	"MDI200058": "Weld Flat Connector",
	**{f"MDI{n}": "FC Dressing Assembly" for n in range(200086, 200094)},
	**{f"MDI{n}": "Pouch Packing and Sealing" for n in [*range(200094, 200101), 200109]},
	**{code: "VivaFoam Packing and Sealing" for code in ("MDI200021", "MDI200035", "MDI200036", "MDI200037", "MDI200025")},
}

NEEDS_CLIENT_INPUT = {"MDI100031", "MDI100036", "MDI100035", "MDI100034", "MDI200059"}

GENERIC_SET_MP_OPERATIONS = ["Pack in Set Box or Multipack", "Assign UDI (Set)", "Pack Transport Boxes"]


def _sterilization_items() -> set[str]:
	return {item for template in STERILIZED_TEMPLATES for item in CHECKPOINT_ITEMS[template]}


def classify(item_code: str, item_group: str, sterilization: set[str]):
	if item_code in CHAIN_OPERATIONS:
		return "chain", [CHAIN_OPERATIONS[item_code]]
	if item_code in sterilization:
		return "sterilization", []
	if item_code in NEEDS_CLIENT_INPUT:
		return "needs_client_input", []
	if item_group == "Finished Product":
		return "generic_set_mp", GENERIC_SET_MP_OPERATIONS
	return "unclassified", []


def run(dry_run: bool = True):
	# fail fast if another session (e.g. an open bench console) is holding locks on these tables
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	sterilization = _sterilization_items()
	attached, skipped, categories = [], [], {}

	for b in frappe.get_all("BOM", filters={"docstatus": ["!=", 2], "is_active": 1}, fields=["name", "item"], order_by="name"):
		item_group = frappe.db.get_value("Item", b.item, "item_group")
		category, operations = classify(b.item, item_group, sterilization)
		categories[category] = categories.get(category, 0) + 1
		if not operations:
			skipped.append((b.name, b.item, category, "no operations by design"))
			continue

		bom = frappe.get_doc("BOM", b.name)
		already = frappe.db.exists(
			"Comment", {"reference_doctype": "BOM", "reference_name": b.name, "content": ["like", f"%{MARKER}%"]}
		)
		if bom.operations or bom.with_operations or already:
			skipped.append((b.name, b.item, category, "already has operations"))
			continue

		for name in operations:
			workstation = frappe.db.get_value("Operation", name, "workstation")
			bom.append("operations", {"operation": name, "workstation": workstation, "time_in_mins": DEFAULT_TIME_MINUTES})

		bom.with_operations = 1
		bom.validate_operations()  # description, batch size; refuses a row without workstation or time
		bom.calculate_op_cost()  # hour rate and cost from the workstation
		bom.total_cost = flt(bom.operating_cost) + flt(bom.raw_material_cost) - flt(bom.scrap_material_cost)
		bom.base_total_cost = flt(bom.base_operating_cost) + flt(bom.base_raw_material_cost) - flt(bom.base_scrap_material_cost)

		stamp = now()
		for row in bom.operations:
			row.name = frappe.generate_hash(length=10)
			row.docstatus = bom.docstatus
			row.creation = row.modified = stamp
			row.owner = row.modified_by = frappe.session.user
			row.db_insert()
		bom.db_update()

		bom.add_comment(
			"Info",
			f"{MARKER}: with_operations set and {len(operations)} operation(s) attached "
			f"({' -> '.join(operations)}), each with a PLACEHOLDER time of {DEFAULT_TIME_MINUTES} min - real "
			"times must come from the client. Written directly because With Operations cannot be changed "
			"after submission. Items, rates and costs unchanged.",
		)
		attached.append((b.name, b.item, category, " -> ".join(operations)))

	summary = {"dry_run": dry_run, "categories": categories, "attached": len(attached), "skipped": len(skipped)}
	frappe.db.rollback() if dry_run else frappe.db.commit()
	print(summary)
	return {"summary": summary, "attached": attached, "skipped": skipped}
