"""One-off: make four sub-assemblies bought-in and retire the old soldered pump (client answer).

MDI100031 (Assembled Back enclosure), MDI100034 (Check Valve with tube), MDI100035 (Front Enclosure
with symbols) and MDI200059 (Extension tube 1m luered) are PURCHASED, not made. The Lagerkoll import
gave each an active default BOM, and three of them are linked as sub-assemblies (BOM Item.bom_no) in
their parent BOMs, so a multi-level Work Order / Production Plan explodes them into their components
and plans to build them. Per item:
- the parent BOM rows keep the item and its quantity/rate, only the bom_no link is cleared, and the
  exploded raw-material list of every affected BOM and its ancestors is rebuilt with ERPNext's own
  update_exploded_items (children first). Rates are not touched, so no BOM cost changes;
- the item's own BOM is kept as history (still submitted) but set inactive and non-default, so it
  can't be picked on a Work Order and bom_operations_attach.py (active BOMs only) never routes it;
- the item moves to the Raw Material group with is_purchase_item=1 and no default BOM. The default
  supplier is left blank for the client to fill in.

MDI100036 (Assembled soldered pump) is OLD: the item and its BOM are disabled - but only while
nothing references it (Work Order, stock ledger, Stock Entry, BOM line, stock or open orders). If
anything does, it is reported and left alone.

Submitted BOMs are written directly (cancel/amend would break the links from item default BOMs,
Subcontracting BOMs and parent BOMs), like the other lagerkoll scripts.

NOT wired into hooks.py or patches.txt, on purpose. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.purchased_items_retire.run

for a DRY RUN (everything is computed, then rolled back), and pass --kwargs "{'dry_run': False}" to
apply. Take a backup first. Everything already in its target state is skipped, so it is safe to run
twice.
"""

import frappe

from medic_customizations.medic_customizations.lagerkoll.bom_quantity_fix import _children_first

MARKER = "Purchased items / retire"

PURCHASED_ITEMS = ("MDI100031", "MDI100034", "MDI100035", "MDI200059")
PURCHASED_ITEM_GROUP = "Raw Material"
RETIRED_ITEMS = ("MDI100036",)

# documents whose existence means an item is still in use and must not be retired
USAGE_CHECKS = (
	("Work Order", "production_item"),
	("Work Order Item", "item_code"),
	("Stock Ledger Entry", "item_code"),
	("Stock Entry Detail", "item_code"),
	("BOM Item", "item_code"),
	("Sales Order Item", "item_code"),
	("Purchase Order Item", "item_code"),
	("Material Request Item", "item_code"),
	("Production Plan Item", "item_code"),
	("Delivery Note Item", "item_code"),
	("Purchase Receipt Item", "item_code"),
)


def _comment(doctype, name, text):
	frappe.get_doc(doctype, name).add_comment("Info", f"{MARKER}: {text}")


def _usage(item_code: str) -> dict:
	usage = {dt: frappe.db.count(dt, {field: item_code}) for dt, field in USAGE_CHECKS}
	usage["Bin (non-zero stock)"] = frappe.db.count("Bin", {"item_code": item_code, "actual_qty": ["!=", 0]})
	return {k: v for k, v in usage.items() if v}


def _deactivate_boms(item_code: str, reason: str) -> list[str]:
	boms = frappe.get_all("BOM", filters={"item": item_code, "docstatus": 1, "is_active": 1}, pluck="name")
	for bom in boms:
		frappe.db.set_value("BOM", bom, {"is_active": 0, "is_default": 0})
		_comment("BOM", bom, f"set inactive and non-default ({reason}). Kept as history.")
	return boms


def _ancestors(boms: set[str]) -> set[str]:
	"""The given BOMs plus every submitted BOM that consumes one of them, directly or further up."""
	found, frontier = set(boms), set(boms)
	while frontier:
		frontier = set(
			frappe.get_all("BOM Item", filters={"bom_no": ["in", list(frontier)], "docstatus": 1}, pluck="parent")
		) - found
		found |= frontier
	return found


def make_purchased(item_code: str, changes: list, relinked: set[str]):
	for row in frappe.get_all(
		"BOM Item",
		filters={"item_code": item_code, "bom_no": ["is", "set"], "docstatus": ["<", 2]},
		fields=["name", "parent", "bom_no"],
	):
		frappe.db.set_value("BOM Item", row.name, "bom_no", "", update_modified=False)
		_comment(
			"BOM", row.parent,
			f"{item_code} is purchased: sub-assembly link to {row.bom_no} removed, so it is bought instead of "
			"built. Quantity and rate unchanged; exploded items rebuilt.",
		)
		relinked.add(row.parent)
		changes.append((item_code, "unlinked sub-assembly BOM in", row.parent))

	for bom in _deactivate_boms(item_code, "item is purchased"):
		changes.append((item_code, "own BOM deactivated", bom))

	item = frappe.get_doc("Item", item_code)
	if item.item_group != PURCHASED_ITEM_GROUP or not item.is_purchase_item or item.default_bom:
		before = (item.item_group, item.is_purchase_item, item.default_bom)
		item.item_group = PURCHASED_ITEM_GROUP
		item.is_purchase_item = 1
		item.default_bom = None
		item.save()
		_comment(
			"Item", item_code,
			f"marked bought-in (client: purchased). Item group {before[0]} -> {PURCHASED_ITEM_GROUP}, "
			f"default BOM {before[2]} cleared. Default supplier left blank.",
		)
		changes.append((item_code, "item updated", f"{before} -> {(PURCHASED_ITEM_GROUP, 1, None)}"))


def retire(item_code: str, changes: list, refused: dict):
	usage = _usage(item_code)
	if usage:
		refused[item_code] = usage
		return

	for bom in _deactivate_boms(item_code, "item retired"):
		changes.append((item_code, "own BOM deactivated", bom))

	if not frappe.db.get_value("Item", item_code, "disabled"):
		item = frappe.get_doc("Item", item_code)
		item.disabled = 1
		item.default_bom = None
		item.save()
		_comment("Item", item_code, "disabled (client: old item, retired). No document referenced it.")
		changes.append((item_code, "item disabled", ""))


def run(dry_run: bool = True):
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	changes, refused, relinked = [], {}, set()

	for item_code in PURCHASED_ITEMS:
		make_purchased(item_code, changes, relinked)
	for item_code in RETIRED_ITEMS:
		retire(item_code, changes, refused)

	rebuilt = _children_first(sorted(_ancestors(relinked))) if relinked else []
	for name in rebuilt:
		bom = frappe.get_doc("BOM", name)
		bom.update_exploded_items()
		bom.db_update()

	summary = {
		"dry_run": dry_run,
		"changes": len(changes),
		"boms_relinked": len(relinked),
		"exploded_items_rebuilt": len(rebuilt),
		"retire_refused": refused,
	}
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for change in changes:
		print("  ", *change)
	print(summary)
	return {"summary": summary, "changes": changes, "rebuilt": rebuilt, "refused": refused}
