"""Work Order print formats reproducing the client's paper form FRM.0112-00.

Two Print Formats share one template (templates/work_order_form/work_order_form.html):
- "FRM.0112 FC Set Packaging Work Order": the client's controlled form, header FRM.0112 / Rev 00 /
  published 2023-10-30, including its Quality Control section. Meant for FC sets with two dressings;
  printed for any other item it carries a visible warning instead of silently looking valid.
- "Work Order Production Form": the same layout for every other product, without a document number
  (none exists for those yet - none is invented) and without the FC-set QC checklist.

The data the template needs comes from work_order_form_context(), registered as a Jinja method in
hooks.py. Nothing here writes data; setup_print_formats() is the only writer and only touches the two
Print Format records.

Set up / update the Print Formats (DRY RUN by default, idempotent):

	bench --site <site> execute medic_customizations.medic_customizations.print_formats.work_order_form.setup_print_formats
	bench --site <site> execute medic_customizations.medic_customizations.print_formats.work_order_form.setup_print_formats --kwargs "{'dry_run': False}"
"""

import base64
import os

import frappe
from frappe.utils import flt, formatdate, getdate

from medic_customizations.medic_customizations.quality_control.inspection import row_batches

TEMPLATE = "medic_customizations/templates/work_order_form/work_order_form.html"
LOGO_PATH = ("public", "images", "sunmedic_logo.png")
MIN_BOM_ROWS = 10  # the paper form has 9; at least 10 so there is always room for hand entry
MIN_JOB_ROWS = 5  # as on the paper form

# The client's controlled form, exactly as printed on FRM.0112-00.
FRM0112 = {
	"title": "FC SET PACKAGING WORK ORDER/CONTROL FORM",
	"document_nr": "FRM.0112",
	"revision_nr": "00",
	"revision_date": "NA",
	"published_date": "2023-10-30",
}

# FRM.0112 quality-control checklist, in the paper form's order and wording.
FRM0112_QC_CHECKS = (
	"One packaged Pump with UDI label",
	"Two FC dressings in PP box",
	"Dressing not damaged/opened",
	"Two void labels on both side of the box",
	"Set UDI label",
	"Inner Box not damaged /rejected",
	"Two void labels on both side of the box",
	"One set IFUs",
)

# FC sets with TWO dressings (PR.015 Table 2e): VivereX 600121-600139, VivereX+ 600420-600439.
# The 1-dressing sets (600140-159 / 600440-459) are left out on purpose: FRM.0112's checklist says
# "Two FC dressings" and has no foam-spacer line (INS.013 Rev03 added that) - client to confirm.
FC_SET_RANGES = (("PDI600121", "PDI600139"), ("PDI600420", "PDI600439"))

PRINT_FORMATS = {
	"FRM.0112 FC Set Packaging Work Order": "frm0112",
	"Work Order Production Form": "generic",
}

ISSUE_PURPOSES = ("Material Transfer for Manufacture", "Manufacture", "Material Consumption for Manufacture")
_logo_cache = {}


def is_fc_set(item_code: str) -> bool:
	return any(low <= (item_code or "") <= high and len(item_code) == len(low) for low, high in FC_SET_RANGES)


def _logo_data_uri() -> str:
	"""The logo inline, so the PDF never depends on the web server serving /assets."""
	if "uri" not in _logo_cache:
		path = frappe.get_app_path("medic_customizations", *LOGO_PATH)
		with open(path, "rb") as f:
			_logo_cache["uri"] = "data:image/png;base64," + base64.b64encode(f.read()).decode()
	return _logo_cache["uri"]


def _date(value) -> str:
	return formatdate(getdate(value), "yyyy-mm-dd") if value else ""


def _qty(value, uom=None) -> str:
	if value in (None, ""):
		return ""
	q = flt(value)
	text = f"{int(q)}" if q == int(q) else f"{q:g}"
	return f"{text} {uom}" if uom else text


def _add(lots: dict, item_code: str, batch: str | None):
	if batch and batch not in lots.setdefault(item_code, []):
		lots[item_code].append(batch)


def finished_lots(wo) -> list[str]:
	"""Lots of the produced item: batches made from this Work Order, and lots booked on its Manufacture entries."""
	lots = {}
	for b in frappe.get_all(
		"Batch", filters={"reference_doctype": "Work Order", "reference_name": wo.name}, pluck="name", order_by="creation"
	):
		_add(lots, wo.production_item, b)
	for se in frappe.get_all("Stock Entry", filters={"work_order": wo.name, "docstatus": 1, "purpose": "Manufacture"}, pluck="name"):
		for row in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": se, "is_finished_item": 1},
			fields=["item_code", "batch_no", "serial_and_batch_bundle", "transfer_qty"],
		):
			for batch, _qty_ in row_batches(row, row.transfer_qty):
				_add(lots, wo.production_item, batch)
	return lots.get(wo.production_item, [])


def issued_lots(wo) -> dict[str, list[str]]:
	"""{component: lots} actually issued on submitted Stock Entries; a submitted Pick List fills in items without one."""
	issued, picked = {}, {}
	for se in frappe.get_all(
		"Stock Entry", filters={"work_order": wo.name, "docstatus": 1, "purpose": ["in", ISSUE_PURPOSES]}, pluck="name"
	):
		for row in frappe.get_all(
			"Stock Entry Detail",
			filters={"parent": se, "s_warehouse": ["is", "set"], "is_finished_item": 0},
			fields=["item_code", "batch_no", "serial_and_batch_bundle", "transfer_qty"],
			order_by="idx",
		):
			for batch, _qty_ in row_batches(row, row.transfer_qty):
				_add(issued, row.item_code, batch)
	for pl in frappe.get_all("Pick List", filters={"work_order": wo.name, "docstatus": 1}, pluck="name"):
		for row in frappe.get_all(
			"Pick List Item",
			filters={"parent": pl},
			fields=["item_code", "batch_no", "serial_and_batch_bundle", "stock_qty"],
			order_by="idx",
		):
			for batch, _qty_ in row_batches(row, row.stock_qty):
				_add(picked, row.item_code, batch)
	for item_code, lots in picked.items():
		if not issued.get(item_code):
			issued[item_code] = lots
	return issued


def job_card_rows(wo) -> list[dict]:
	rows = []
	for jc in frappe.get_all(
		"Job Card",
		filters={"work_order": wo.name, "docstatus": ["<", 2]},
		fields=["name", "operation", "workstation"],
		order_by="creation asc, name asc",
	):
		employees = []
		for emp in frappe.get_all(
			"Job Card Time Log", filters={"parent": jc.name, "parenttype": "Job Card"}, pluck="employee", order_by="idx"
		):
			if emp and emp not in employees:
				employees.append(emp)
		names = [frappe.db.get_value("Employee", e, "employee_name") or e for e in employees]
		rows.append({"operator": ", ".join(names), "activity": jc.operation or "", "equipment": jc.workstation or ""})
	return rows


def work_order_form_context(doc, variant: str = "generic") -> dict:
	"""Everything the Work Order form template prints (Jinja method, see hooks.py)."""
	wo = doc
	operations = [op.operation for op in (wo.get("operations") or []) if op.operation]
	if not operations and wo.get("bom_no"):
		operations = frappe.get_all("BOM Operation", filters={"parent": wo.bom_no}, pluck="operation", order_by="idx")

	issued = issued_lots(wo) if wo.name and not wo.is_new() else {}
	bom_rows = [
		{
			"description": row.item_name or row.item_code,
			"quantity": _qty(row.required_qty, row.stock_uom),
			"article_no": row.item_code,
			"lot_no": ", ".join(issued.get(row.item_code, [])),
			"quantity_used": _qty(row.consumed_qty, row.stock_uom) if flt(row.consumed_qty) else "",
		}
		for row in (wo.get("required_items") or [])
	]
	bom_rows += [{}] * max(0, MIN_BOM_ROWS - len(bom_rows))

	jobs = job_card_rows(wo) if wo.name and not wo.is_new() else []
	jobs += [{}] * max(0, MIN_JOB_ROWS - len(jobs))

	fc_set = is_fc_set(wo.production_item)
	return {
		"variant": variant,
		"logo": _logo_data_uri(),
		"form": FRM0112 if variant == "frm0112" else None,
		"wrong_form": variant == "frm0112" and not fc_set,
		"work_order_no": wo.name or "",
		"product_description": wo.item_name or wo.production_item or "",
		"lot_number": ", ".join(finished_lots(wo)) if wo.name and not wo.is_new() else "",
		"proposed_date": _date(wo.planned_start_date),
		"qty": _qty(wo.qty, wo.get("stock_uom")),
		"operations": operations,
		"start_date": _date(wo.actual_start_date),
		"end_date": _date(wo.actual_end_date),
		"bom_rows": bom_rows,
		"jobs": jobs,
		"qc_checks": FRM0112_QC_CHECKS if variant == "frm0112" else (),
	}


def _desired(name: str, variant: str) -> dict:
	return {
		"doctype": "Print Format",
		"name": name,
		"doc_type": "Work Order",
		"module": "Medic Customizations",
		"standard": "No",
		"custom_format": 1,
		"print_format_type": "Jinja",
		"disabled": 0,
		"raw_printing": 0,
		"print_format_builder": 0,
		"html": f'{{% set variant = "{variant}" %}}{{% include "{TEMPLATE}" %}}',
		"css": "",
	}


def apply() -> list:
	"""Create or update the two Print Formats (no commit / rollback here)."""
	changes = []
	for name, variant in PRINT_FORMATS.items():
		desired = _desired(name, variant)
		if not frappe.db.exists("Print Format", name):
			frappe.get_doc(desired).insert()
			changes.append((name, "created"))
			continue
		pf = frappe.get_doc("Print Format", name)
		diff = [k for k, v in desired.items() if k not in ("doctype", "name") and (pf.get(k) or "") != (v or "")]
		if diff:
			pf.update({k: desired[k] for k in diff})
			pf.save()
			changes.append((name, f"updated: {', '.join(diff)}"))
		else:
			changes.append((name, "unchanged"))
	return changes


def setup_print_formats(dry_run: bool = True):
	changes = apply()
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for change in changes:
		print("  ", *change)
	print({"dry_run": dry_run})
	return changes
