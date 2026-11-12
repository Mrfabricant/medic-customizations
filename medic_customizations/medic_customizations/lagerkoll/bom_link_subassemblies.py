"""One-off (DRY RUN unless told otherwise): link every sub-assembly row that is missing its BOM link.

A BOM row whose item is itself made here (the item has an active, submitted default BOM and is not
disabled) should point at that BOM (BOM Item.bom_no). Without the link:
- the row is priced at the item's valuation rate instead of its BOM cost;
- Production Plan "Get Sub Assembly Items" does not see it, so no Work Order / Subcontracting Order
  is planned for it - the chain stops there (e.g. the VivereX pump chain stopped at MDI100040,
  whose BOM lists MDI100045 unlinked while VivereX+ MDI100067 links it).
Purchased items are excluded automatically: their own BOMs were deactivated (purchased_items_retire),
and retired items are disabled.

Apply: the candidate rows get bom_no = the child's default BOM; then every affected BOM and every BOM
above it is recomputed children first with ERPNext's own formula (sub-assembly rate = child BOM unit
cost via get_rm_rate when the BOM prices sub-assemblies from their BOM), amounts, totals and exploded
items - the same direct write as the other lagerkoll scripts. Purchased-item rates and quantities are
never changed. Supersedes the link part of set_bom_dressing_links.py (running both is harmless: an
already linked row is skipped).

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_link_subassemblies.run
	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_link_subassemblies.run --kwargs "{'dry_run': False}"
	(leave rows out: --kwargs "{'dry_run': False, 'exclude': ['BOM-XYZ-001:MDI100066']}")
"""

import frappe
from frappe.utils import flt

from medic_customizations.medic_customizations.lagerkoll.adhesive_strips_fix import _recompute_row, _recompute_totals
from medic_customizations.medic_customizations.lagerkoll.bom_quantity_fix import ROLL_ROWS, _children_first

MARKER = "Sub-assembly BOM link"

# Items cut from a roll (Holed/Unholed TPU film from the TPU roll, cut 3D mesh from the mesh roll). Their
# BOMs hold the whole roll consumption on a BOM quantity of 1 (225 Kg TPU / 28 rolls of mesh per piece:
# 14,625 / 756 per unit), so linking them would push ~30,000 into every dressing, set and multipack.
# HELD until those BOMs carry the real yield per roll (client: pieces per Kg TPU / per mesh roll).
HELD_ITEMS = frozenset(parent for parent, _component in ROLL_ROWS)


def candidates() -> list[dict]:
	"""Rows in active submitted BOMs whose child has an active default BOM but the row has no BOM link."""
	return frappe.db.sql(
		"""select bi.name as row_name, bi.parent, b.item as parent_item, bi.idx, bi.item_code, bi.item_name, bi.qty, bi.rate,
			i.default_bom as child_bom, i.is_sub_contracted_item, i.item_group as child_group,
			cb.total_cost / cb.quantity as child_unit_cost, b.set_rate_of_sub_assembly_item_based_on_bom as rate_from_bom
		from `tabBOM Item` bi
		join tabBOM b on b.name = bi.parent and b.docstatus = 1 and b.is_active = 1
		join tabItem i on i.name = bi.item_code and i.disabled = 0 and ifnull(i.default_bom, '') != ''
		join tabBOM cb on cb.name = i.default_bom and cb.docstatus = 1 and cb.is_active = 1
		where bi.parenttype = 'BOM' and ifnull(bi.bom_no, '') = ''
		order by b.item, bi.idx""",
		as_dict=True,
	)


def apply(exclude: list[str] | None = None) -> dict:
	exclude = set(exclude or [])
	found = candidates()
	held = [r for r in found if r.item_code in HELD_ITEMS]
	rows = [r for r in found if r.item_code not in HELD_ITEMS and f"{r.parent}:{r.item_code}" not in exclude]
	all_boms = frappe.get_all("BOM", filters={"docstatus": 1, "is_active": 1}, pluck="name")
	before = {b.name: flt(b.total_cost) for b in frappe.get_all("BOM", filters={"name": ["in", all_boms]}, fields=["name", "total_cost"])}

	for r in rows:  # links first, so the children-first order below already follows the new links
		frappe.db.set_value("BOM Item", r.row_name, "bom_no", r.child_bom, update_modified=False)
	linked_parents = {r.parent for r in rows}

	changed = set()
	for name in _children_first(all_boms):
		bom = frappe.get_doc("BOM", name)
		touched = name in linked_parents or any(row.bom_no in changed for row in bom.items)
		if not touched:
			continue
		for row in bom.items:
			if row.bom_no and (row.bom_no in changed or name in linked_parents) and bom.set_rate_of_sub_assembly_item_based_on_bom:
				new_rate = bom.get_rm_rate(
					{"item_code": row.item_code, "bom_no": row.bom_no, "conversion_factor": row.conversion_factor,
					"sourced_by_supplier": row.sourced_by_supplier},
					notify=False,
				)
				if abs(flt(new_rate) - flt(row.rate)) >= 1e-9:
					row.rate = new_rate
					_recompute_row(bom, row)
					row.db_update()
		_recompute_totals(bom)
		if name in linked_parents:
			mine = [r for r in rows if r.parent == name]
			bom.add_comment(
				"Info",
				f"{MARKER}: " + "; ".join(f"{r.item_code} -> {r.child_bom}" for r in mine)
				+ ". Sub-assembly rates from the child BOMs (ERPNext get_rm_rate); totals and exploded items recomputed.",
			)
		changed.add(name)

	after = {b.name: flt(b.total_cost) for b in frappe.get_all("BOM", filters={"name": ["in", list(changed)]}, fields=["name", "total_cost"])}
	costs = sorted((n, frappe.db.get_value("BOM", n, "item"), before[n], after[n]) for n in changed if abs(before[n] - after[n]) >= 0.005)
	return {"rows": rows, "held": held, "linked_parents": sorted(linked_parents), "boms_recomputed": len(changed), "cost_changes": costs}


def run(dry_run: bool = True, exclude: list[str] | None = None):
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	result = apply(exclude)
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	by_parent = {}
	for r in result["rows"]:
		by_parent.setdefault((r.parent_item, r.parent), []).append(r)
	for (item, bom), rows in by_parent.items():
		print(f"   {item} ({bom})")
		for r in rows:
			kind = "subcontracted" if r.is_sub_contracted_item else "in-house"
			print(f"      {r.item_code} {r.item_name[:34]} x{flt(r.qty):g}: rate {flt(r.rate):.2f} -> BOM {r.child_bom} "
				f"(unit cost {flt(r.child_unit_cost):.2f}, {kind})" + ("" if r.rate_from_bom else "  [parent keeps manual rates]"))
	for r in result["held"]:
		print(f"   HELD {r.parent_item} ({r.parent}): {r.item_code} {r.item_name[:30]} - its BOM costs {flt(r.child_unit_cost):.2f} per piece "
			"(whole roll on BOM qty 1); link only after the yield per roll is set")
	print(f"   cost changes ({len(result['cost_changes'])} BOMs):")
	for name, item, b, a in result["cost_changes"]:
		print(f"      {item} {name}: {b:.2f} -> {a:.2f}")
	print({"dry_run": dry_run, "rows_linked": len(result["rows"]), "rows_held": len(result["held"]), "parent_boms": len(result["linked_parents"]),
		"boms_recomputed": result["boms_recomputed"]})
	return result
