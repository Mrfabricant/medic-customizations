"""One-off correction of the 10x overstated BOM component quantities in the Lagerkoll import.

Evidence: every multipack BOM whose real size is in its own item name (24, 36, 48, 72, "Multipack of
30") carries a component quantity exactly 10x that size, and 574 of the imported rows sit at exactly 10.
The Lagerkoll "amount of part article" was exported 10x too high.

NOT wired into hooks.py or patches.txt, on purpose: it is a manual, one-time data correction and it
must not run on a site (production) until someone decides to. Run it with

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_quantity_fix.run

which is a DRY RUN (everything is computed, then rolled back). To apply, pass dry_run=False:

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.bom_quantity_fix.run \\
		--kwargs "{'dry_run': False}"

Take a backup first (bench --site <site> backup). It refuses to divide a BOM twice: every BOM it
changes gets an audit comment starting with MARKER, and a BOM carrying it is skipped.

What it changes, per BOM (children before parents):
- a row's quantity is divided by 10, except the rows listed under ROLL_ROWS and any row whose result
  would not be a whole number (those are reported as held, not changed);
- the quantities of the already-corrected sterilization BOMs are not touched;
- rates of purchased items and every Sourced-by-Supplier flag are left alone. A sub-assembly row's
  rate is not a price: ERPNext derives it from the child BOM's cost per unit, so it is recomputed with
  ERPNext's own formula (get_rm_rate) or the tree would be internally inconsistent;
- the row amounts, the BOM totals and the exploded raw-material list are recomputed. The BOMs are
  submitted, so this is done directly instead of cancel/amend, which would break the links from
  item default BOMs, Subcontracting BOMs and parent BOMs. ERPNext's Update Cost is not used: it
  would re-price every purchased item from current valuation rates.
"""

import frappe
from frappe.utils import flt

from medic_customizations.medic_customizations.setup import CHECKPOINT_ITEMS, STERILIZED_TEMPLATES

DIVISOR = 10
MARKER = "BOM quantity scale fix"

# (BOM item, component) rows that consume a raw roll/film: the quantity is material consumption, not a
# unit count, so it is not scaled.
ROLL_ROWS = {
	("MDI200079", "MDI200122"),  # Holed TPU film <- TPU roll
	("MDI200080", "MDI200122"),  # Unholed TPU film <- TPU roll
	("MDI200123", "MDI200050"),  # Cut 3D mesh <- mesh roll
}


def _sterilization_boms() -> set[str]:
	boms = set()
	for template in STERILIZED_TEMPLATES:
		for item_code in CHECKPOINT_ITEMS[template]:
			bom = frappe.db.get_value("Item", item_code, "default_bom")
			if bom:
				boms.add(bom)
	return boms


def _children_first(names: list[str]) -> list[str]:
	"""BOM names ordered so that every BOM comes after the BOMs it consumes."""
	links = {}
	for name in names:
		links[name] = set(
			frappe.get_all("BOM Item", filters={"parent": name, "bom_no": ["is", "set"]}, pluck="bom_no")
		) & set(names)

	ordered, seen = [], set()

	def visit(name, path=()):
		if name in seen or name in path:
			return
		for child in sorted(links[name]):
			visit(child, (*path, name))
		seen.add(name)
		ordered.append(name)

	for name in sorted(names):
		visit(name)
	return ordered


def _decide(bom: str, parent_item: str, row, sterilization: set[str]):
	"""('divide', new_qty) | ('roll', None) | ('held', None) | ('skip', None)."""
	if bom in sterilization:
		return "skip", None
	if (parent_item, row.item_code) in ROLL_ROWS:
		return "roll", None
	new_qty = flt(row.qty) / DIVISOR
	if abs(new_qty - round(new_qty)) > 1e-9 or round(new_qty) < 1:
		return "held", None
	return "divide", float(round(new_qty))


def run(dry_run: bool = True):
	sterilization = _sterilization_boms()
	names = _children_first(frappe.get_all("BOM", filters={"docstatus": 1}, pluck="name"))
	touched, report, held, rolls = set(), [], [], []

	for name in names:
		bom = frappe.get_doc("BOM", name)
		already = frappe.db.exists(
			"Comment", {"reference_doctype": "BOM", "reference_name": name, "content": ["like", f"%{MARKER}%"]}
		)
		cost_before = flt(bom.total_cost)
		n_divided, n_rate, row_changed = 0, 0, False

		for row in bom.items:
			old_qty, old_rate = flt(row.qty), flt(row.rate)

			action, new_qty = ("skip", None) if already else _decide(name, bom.item, row, sterilization)
			if action == "divide":
				row.qty = new_qty
				n_divided += 1
			elif action == "held":
				held.append((name, bom.item, row.item_code, row.item_name, old_qty))
			elif action == "roll":
				rolls.append((name, bom.item, row.item_code, row.item_name, old_qty, row.uom))

			# a sub-assembly's rate is derived from its child BOM's cost per unit (ERPNext's own formula)
			if row.bom_no and bom.set_rate_of_sub_assembly_item_based_on_bom:
				row.rate = bom.get_rm_rate(
					{
						"item_code": row.item_code,
						"bom_no": row.bom_no,
						"conversion_factor": row.conversion_factor,
						"sourced_by_supplier": row.sourced_by_supplier,
					},
					notify=False,
				)

			if flt(row.qty) == old_qty and abs(flt(row.rate) - old_rate) < 1e-9:
				continue

			row_changed = True
			n_rate += 1 if abs(flt(row.rate) - old_rate) >= 1e-9 else 0
			row.stock_qty = flt(row.qty) * flt(row.conversion_factor or 1)
			row.qty_consumed_per_unit = flt(row.stock_qty) / flt(bom.quantity)
			row.base_rate = flt(row.rate) * flt(bom.conversion_rate)
			row.amount = flt(flt(row.rate, row.precision("rate")) * flt(row.qty, row.precision("qty")), row.precision("amount"))
			row.base_amount = flt(row.amount) * flt(bom.conversion_rate)
			row.db_update()

		children = set(r.bom_no for r in bom.items if r.bom_no)
		if not (row_changed or children & touched):
			report.append({"bom": name, "item": bom.item, "divided": 0, "rates": 0, "before": cost_before, "after": cost_before})
			continue

		touched.add(name)
		bom.raw_material_cost = sum(flt(r.amount) for r in bom.items)
		bom.base_raw_material_cost = sum(flt(r.base_amount) for r in bom.items)
		bom.total_cost = flt(bom.operating_cost) + bom.raw_material_cost - flt(bom.scrap_material_cost)
		bom.base_total_cost = flt(bom.base_operating_cost) + bom.base_raw_material_cost - flt(bom.base_scrap_material_cost)
		bom.update_exploded_items()
		bom.db_update()

		if not already:
			bom.add_comment(
				"Info",
				f"{MARKER}: {n_divided} row quantities divided by {DIVISOR} (Lagerkoll amounts were exported "
				f"{DIVISOR}x too high); {n_rate} rate(s) recomputed from child BOM cost; costs and exploded "
				"raw materials recomputed. Purchased-item rates and Sourced-by-Supplier flags untouched."
				+ (" Quantities not changed on this BOM (sterilization ratio already corrected)." if name in sterilization else ""),
			)
		report.append({"bom": name, "item": bom.item, "divided": n_divided, "rates": n_rate, "before": cost_before, "after": flt(bom.total_cost)})

	summary = {
		"dry_run": dry_run,
		"boms": len(names),
		"boms_touched": len(touched),
		"rows_divided": sum(r["divided"] for r in report),
		"rows_held": len(held),
		"roll_exceptions": len(rolls),
	}
	if dry_run:
		frappe.db.rollback()
	else:
		frappe.db.commit()
	print(summary)
	return {"summary": summary, "report": report, "held": held, "rolls": rolls}
