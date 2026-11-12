"""One-off (DRY RUN unless told otherwise): link the FC dressings in the VivereX set BOMs to their BOM.

In the VivereX sets PDI600121-128 (2 dressings) and PDI600141-148 (1 dressing) the sterile FC
dressing row (PDI600221-228) has no BOM No, while the same dressing in the VivereX+ sets
PDI600421-428 is linked. Without the link:
- the row is priced at the dressing's valuation rate, not its BOM cost, so the set cost ignores the
  dressing BOM (the adhesive-strip correction never reached these sets);
- a Production Plan's "Get Sub Assembly Items" does not see the dressing as a sub-assembly, so it
  plans no Subcontracting (sterilization) for it - only a purchase of the dressing.

Per row: BOM No = the dressing's default BOM, rate recomputed with ERPNext's own get_rm_rate (the set
BOMs price sub-assemblies from the child BOM), then amounts, totals and the exploded list - the same
direct write as the other lagerkoll scripts (the BOMs are submitted; cancel/amend would break links).
Nothing consumes these sets, so no other BOM changes. Quantities are NOT changed, except:

PDI600125 ("set 1 pump 2 dressing FC 16x21") carries the dressing at qty 1 where every sibling has 2.
That is only changed when the client confirms it, by passing pdi600125_dressing_qty=2. Its void label
(1 vs 2) and 9-DE/IT IFU (2 vs 1) rows also differ from the siblings - reported, never changed here.

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.set_bom_dressing_links.run
	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.set_bom_dressing_links.run --kwargs "{'dry_run': False}"
	(with the client's confirmation: --kwargs "{'dry_run': False, 'pdi600125_dressing_qty': 2}")

Rows already linked are skipped and a BOM carrying the MARKER comment is not touched again, so it is
safe to run twice.
"""

import frappe
from frappe.utils import flt

from medic_customizations.medic_customizations.lagerkoll.adhesive_strips_fix import _recompute_row, _recompute_totals

MARKER = "Set BOM dressing link"
SETS = [f"PDI{n}" for n in (*range(600121, 600129), *range(600141, 600149))]
DRESSINGS = [f"PDI{n}" for n in range(600221, 600229)]
PDI600125 = "PDI600125"
SIBLINGS_OF_125 = ("PDI600124", "PDI600126")


def _row_qty(bom: str, item_code: str):
	return frappe.db.get_value("BOM Item", {"parent": bom, "item_code": item_code}, "qty")


def pdi600125_report() -> list:
	"""Rows of PDI600125 whose quantity differs from both 2-dressing siblings."""
	bom = frappe.db.get_value("Item", PDI600125, "default_bom")
	siblings = [frappe.db.get_value("Item", s, "default_bom") for s in SIBLINGS_OF_125]
	out = []
	for row in frappe.get_all("BOM Item", filters={"parent": bom}, fields=["item_code", "item_name", "qty"], order_by="idx"):
		sib = [_row_qty(b, row.item_code) for b in siblings]
		if all(s is not None and flt(s) != flt(row.qty) for s in sib):
			out.append((row.item_code, row.item_name, flt(row.qty), [flt(s) for s in sib]))
	return out


def apply(pdi600125_dressing_qty: float | None = None) -> dict:
	report, linked, skipped = [], 0, []
	for set_item in SETS:
		bom_name = frappe.db.get_value("Item", set_item, "default_bom")
		if not bom_name:
			skipped.append((set_item, "no default BOM"))
			continue
		marked = frappe.db.exists(
			"Comment", {"reference_doctype": "BOM", "reference_name": bom_name, "content": ["like", f"%{MARKER}%"]}
		)
		bom = frappe.get_doc("BOM", bom_name)
		before = flt(bom.total_cost)
		changes = []
		for row in bom.items:
			if row.item_code not in DRESSINGS:
				continue
			new_qty = None
			if set_item == PDI600125 and pdi600125_dressing_qty and flt(row.qty) != flt(pdi600125_dressing_qty):
				new_qty = flt(pdi600125_dressing_qty)
			if (row.bom_no or marked) and new_qty is None:
				continue
			dressing_bom = frappe.db.get_value("Item", row.item_code, "default_bom")
			if not dressing_bom:
				skipped.append((set_item, f"{row.item_code} has no default BOM"))
				continue
			old_rate, old_qty = flt(row.rate), flt(row.qty)
			row.bom_no = row.bom_no or dressing_bom
			if new_qty is not None:
				row.qty = new_qty
			if bom.set_rate_of_sub_assembly_item_based_on_bom:
				row.rate = bom.get_rm_rate(
					{"item_code": row.item_code, "bom_no": row.bom_no, "conversion_factor": row.conversion_factor,
					"sourced_by_supplier": row.sourced_by_supplier},
					notify=False,
				)
			_recompute_row(bom, row)
			row.db_update()
			changes.append(
				f"{row.item_code} -> {row.bom_no}, rate {old_rate:.2f} -> {flt(row.rate):.2f}"
				+ (f", qty {old_qty:g} -> {flt(row.qty):g}" if new_qty is not None else "")
			)
		if not changes:
			skipped.append((set_item, "already linked" if not marked else "marker present"))
			continue
		_recompute_totals(bom)
		bom.add_comment(
			"Info",
			f"{MARKER}: {'; '.join(changes)}. Rate from the dressing BOM (ERPNext get_rm_rate); amounts, totals and "
			"exploded items recomputed.",
		)
		linked += 1
		report.append((set_item, bom_name, "; ".join(changes), before, flt(bom.total_cost)))
	return {"report": report, "skipped": skipped, "boms_changed": linked, "pdi600125_rows_differing": pdi600125_report()}


def run(dry_run: bool = True, pdi600125_dressing_qty: float | None = None):
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	result = apply(pdi600125_dressing_qty)
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for set_item, bom, change, before, after in result["report"]:
		print(f"   {set_item} {bom}: {change} | set cost {before:.2f} -> {after:.2f}")
	for s in result["skipped"]:
		print("   skipped:", *s)
	print("   PDI600125 rows differing from PDI600124/126:", result["pdi600125_rows_differing"])
	print({"dry_run": dry_run, "boms_changed": result["boms_changed"]})
	return result
