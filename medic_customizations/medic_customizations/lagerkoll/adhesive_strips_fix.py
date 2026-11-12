"""One-off: 6 fixation strips of ONE size per dressing package (client, INS.034).

The sterile dressing PDI6002xx is made from its unsterilized pouch (MDI2000xx) plus the sterilization
service; the strips are a component of that pouch BOM. The Lagerkoll import gave every pouch BOM one
strip at qty 1 (after the /10 fix), and BOM-MDI200094-001 (10x30) carried BOTH sizes. Per the client:
the 5x35 strip is used on PDI600223 (10x40) only, every other size uses the 5x30 strip.

Per pouch BOM: the correct-size strip row is set to STRIP_QTY, any other-size strip row is removed,
and what depends on it is recomputed the same way as bom_quantity_fix.py: the row amount, the BOM
totals and the exploded raw-material list, then - children first - the sub-assembly rates, totals and
exploded lists of every BOM above it (the sterile dressing, and anything consuming that). Purchased
item rates are not touched. The BOMs are submitted, so this is a direct DB write, not cancel/amend
(which would break the links from item default BOMs, Subcontracting BOMs and parent BOMs).

Order with bom_quantity_fix.py: that script skips the rows in STRIP_ROWS, so the two can run in either
order and end in the same state (the /10 fix is not applied on production yet).

Refuses to change anything if a pouch is consumed by any BOM other than its own dressing's (a shared
pouch could need two strip sizes), or if a dressing's BOM no longer points at the expected pouch.

NOT wired into hooks.py or patches.txt, on purpose. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.adhesive_strips_fix.run

for a DRY RUN (everything is computed, then rolled back), and pass --kwargs "{'dry_run': False}" to
apply. Take a backup first. A pouch BOM that carries the MARKER comment, or is already in the target
state, is skipped, so it is safe to run twice.
"""

import frappe
from frappe.utils import flt

MARKER = "Adhesive strips fix"
STRIP_QTY = 6
STRIP_5X30 = "MDI200060"
STRIP_5X35 = "MDI200101"
STRIP_ITEMS = (STRIP_5X30, STRIP_5X35)

# sterile dressing -> (its unsterilized pouch item, the one strip size it uses)
DRESSINGS = {
	"PDI600221": ("MDI200109", STRIP_5X30),  # 10x20
	"PDI600222": ("MDI200094", STRIP_5X30),  # 10x30 - its pouch BOM also carries a 5x35 row, removed
	"PDI600223": ("MDI200095", STRIP_5X35),  # 10x40
	"PDI600224": ("MDI200096", STRIP_5X30),  # 16x16
	"PDI600225": ("MDI200097", STRIP_5X30),  # 16x21
	"PDI600226": ("MDI200098", STRIP_5X30),  # 16x31
	"PDI600227": ("MDI200099", STRIP_5X30),  # 21x21
	"PDI600228": ("MDI200100", STRIP_5X30),  # 26x26
}

# (BOM item, component) rows owned by this script; bom_quantity_fix.py leaves them alone.
STRIP_ROWS = frozenset((pouch, strip) for pouch, strip in DRESSINGS.values())


def _recompute_row(bom, row):
	row.stock_qty = flt(row.qty) * flt(row.conversion_factor or 1)
	row.qty_consumed_per_unit = flt(row.stock_qty) / flt(bom.quantity)
	row.base_rate = flt(row.rate) * flt(bom.conversion_rate)
	row.amount = flt(flt(row.rate, row.precision("rate")) * flt(row.qty, row.precision("qty")), row.precision("amount"))
	row.base_amount = flt(row.amount) * flt(bom.conversion_rate)


def _recompute_totals(bom):
	bom.raw_material_cost = sum(flt(r.amount) for r in bom.items)
	bom.base_raw_material_cost = sum(flt(r.base_amount) for r in bom.items)
	bom.total_cost = flt(bom.operating_cost) + bom.raw_material_cost - flt(bom.scrap_material_cost)
	bom.base_total_cost = flt(bom.base_operating_cost) + bom.base_raw_material_cost - flt(bom.base_scrap_material_cost)
	bom.update_exploded_items()  # rebuilt from the in-memory rows and the children's stored explosions
	bom.db_update()


def _check_pouches() -> dict[str, str]:
	"""{dressing: pouch BOM}. Throws before anything is written if the structure isn't the traced one."""
	problems, pouch_boms = [], {}
	for dressing, (pouch, strip) in DRESSINGS.items():
		dressing_bom = frappe.db.get_value("Item", dressing, "default_bom")
		row = frappe.db.get_value(
			"BOM Item", {"parent": dressing_bom, "item_code": pouch}, ["bom_no"], as_dict=True
		) if dressing_bom else None
		if not row or not row.bom_no:
			problems.append(f"{dressing}: default BOM {dressing_bom} has no sub-assembly row for {pouch}")
			continue
		pouch_boms[dressing] = row.bom_no

		consumers = frappe.get_all(
			"BOM Item",
			filters={"item_code": pouch, "docstatus": ["<", 2], "parenttype": "BOM"},
			fields=["parent"],
			pluck="parent",
		)
		for parent in set(consumers):
			parent_item = frappe.db.get_value("BOM", parent, "item")
			needed = DRESSINGS.get(parent_item, (None, None))[1]
			if parent_item != dressing:
				problems.append(
					f"pouch {pouch} is shared: also consumed by {parent} ({parent_item}, strip "
					f"{needed or 'unknown'}) besides {dressing} (strip {strip})"
				)
	if problems:
		frappe.throw("Adhesive strips fix refused, nothing changed:<br>" + "<br>".join(problems))
	return pouch_boms


def _ancestors(boms: set[str]) -> list[str]:
	"""Every submitted BOM consuming one of `boms`, directly or further up, ordered children first."""
	parents_of, found, frontier = {}, set(), set(boms)
	while frontier:
		rows = frappe.get_all(
			"BOM Item", filters={"bom_no": ["in", list(frontier)], "docstatus": 1}, fields=["parent", "bom_no"]
		)
		for r in rows:
			parents_of.setdefault(r.parent, set()).add(r.bom_no)
		frontier = {r.parent for r in rows} - found - boms
		found |= frontier

	ordered, seen = [], set()

	def visit(name):
		if name in seen:
			return
		seen.add(name)
		for child in sorted(parents_of.get(name, ()) & found):
			visit(child)
		ordered.append(name)

	for name in sorted(found):
		visit(name)
	return ordered


def fix_pouch(dressing: str, pouch_bom: str, report: list) -> bool:
	pouch, strip = DRESSINGS[dressing]
	bom = frappe.get_doc("BOM", pouch_bom)
	cost_before = flt(bom.total_cost)
	strips = [r for r in bom.items if r.item_code in STRIP_ITEMS]
	correct = [r for r in strips if r.item_code == strip]
	wrong = [r for r in strips if r.item_code != strip]
	entry = {
		"dressing": dressing, "pouch": pouch, "bom": pouch_bom, "strip": strip,
		"rows_before": [(r.item_code, flt(r.qty)) for r in strips],
	}
	report.append(entry)

	marked = frappe.db.exists(
		"Comment", {"reference_doctype": "BOM", "reference_name": pouch_bom, "content": ["like", f"%{MARKER}%"]}
	)
	if marked or (len(correct) == 1 and flt(correct[0].qty) == STRIP_QTY and not wrong):
		entry["action"] = "skipped (already done)"
		return False
	if len(correct) != 1:
		entry["action"] = f"REFUSED: expected one {strip} row, found {len(correct)}"
		return False

	row = correct[0]
	row.qty = STRIP_QTY
	_recompute_row(bom, row)
	row.db_update()

	wrong_names = {r.name for r in wrong}
	for name in wrong_names:
		frappe.db.delete("BOM Item", {"name": name})
	bom.items = [r for r in bom.items if r.name not in wrong_names]
	for idx, r in enumerate(bom.items, start=1):
		if r.idx != idx:
			r.idx = idx
			r.db_update()

	_recompute_totals(bom)
	bom.add_comment(
		"Info",
		f"{MARKER}: {strip} set to {STRIP_QTY} per package (client, INS.034: 6 fixation strips of one size)"
		+ (f"; other-size strip row(s) {', '.join(f'{r.item_code} x{flt(r.qty):g}' for r in wrong)} removed" if wrong else "")
		+ ". Row amount, totals and exploded items recomputed; purchased-item rates untouched.",
	)
	entry["action"] = "fixed"
	entry["rows_after"] = [(r.item_code, flt(r.qty)) for r in bom.items if r.item_code in STRIP_ITEMS]
	entry["cost"] = (cost_before, flt(bom.total_cost))
	return True


def propagate(changed: set[str]) -> list:
	"""Recompute sub-assembly rates, totals and explosions of every BOM above `changed`, children first."""
	costs, updated = [], set(changed)
	for name in _ancestors(changed):
		bom = frappe.get_doc("BOM", name)
		before = flt(bom.total_cost)
		touched = False
		for row in bom.items:
			if row.bom_no not in updated:
				continue
			touched = True
			if bom.set_rate_of_sub_assembly_item_based_on_bom:
				row.rate = bom.get_rm_rate(
					{
						"item_code": row.item_code,
						"bom_no": row.bom_no,
						"conversion_factor": row.conversion_factor,
						"sourced_by_supplier": row.sourced_by_supplier,
					},
					notify=False,
				)
			_recompute_row(bom, row)
			row.db_update()
		if touched:
			_recompute_totals(bom)
			updated.add(name)
			costs.append((name, bom.item, before, flt(bom.total_cost)))
	return costs


def apply() -> dict:
	"""The change itself, without commit or rollback (run() decides)."""
	pouch_boms = _check_pouches()
	report, changed = [], set()
	for dressing in DRESSINGS:
		if fix_pouch(dressing, pouch_boms[dressing], report):
			changed.add(pouch_boms[dressing])
	ancestors = propagate(changed) if changed else []
	summary = {
		"pouch_boms_fixed": len(changed),
		"skipped_or_refused": len(report) - len(changed),
		"ancestor_boms_recomputed": len(ancestors),
	}
	return {"summary": summary, "report": report, "ancestors": ancestors}


def run(dry_run: bool = True):
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	result = apply()
	result["summary"]["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for e in result["report"]:
		print("  ", e["dressing"], e["bom"], e["rows_before"], "->", e.get("rows_after"), e["action"], e.get("cost", ""))
	for a in result["ancestors"]:
		print("   ancestor", *a)
	print(result["summary"])
	return result
