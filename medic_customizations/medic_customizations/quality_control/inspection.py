import frappe
from frappe import _
from frappe.utils import flt

PUMP_PRE_ASSEMBLY_CHECK = "Pump Pre-Assembly Check (INS.036, consolidated Steps 1-4)"
PUMP_FINAL_CONTROL = "Pump Final Control (INS.040)"
FLAT_CONNECTOR_QC = "Flat Connector QC (INS.033/INS.039)"
FC_DRESSING_ASSEMBLY_CHECK = "FC Dressing Assembly Check (INS.032)"
DRESSING_FINAL_CONTROL = "Dressing Final Control (INS.034)"
VIVAFOAM_FINAL_CONTROL = "VivaFoam Final Control (INS.037)"
PRE_STERILIZATION_CHECK_DRESSING = "Pre-Sterilization Shipment Check (INS.031)"
PRE_STERILIZATION_CHECK_VIVAFOAM = "Pre-Sterilization Shipment Check (INS.041)"

# Quality Inspection Templates allowed to act as a per-unit blocking gate. Every one of them is a
# 100%-control check: each unit is inspected. Never add a sampling-based template to this set -
# a sample cannot vouch for every individual unit of a medical device.
GATING_TEMPLATES = frozenset(
	{
		PRE_STERILIZATION_CHECK_DRESSING,
		PRE_STERILIZATION_CHECK_VIVAFOAM,
		PUMP_PRE_ASSEMBLY_CHECK,
		PUMP_FINAL_CONTROL,
		FLAT_CONNECTOR_QC,
		FC_DRESSING_ASSEMBLY_CHECK,
		DRESSING_FINAL_CONTROL,
		VIVAFOAM_FINAL_CONTROL,
	}
)

# INS.046 "Combination Functionality Test" tests 0.3% of a lot by design, so it can never gate
# individual units. It may exist as a separate, non-blocking lot-level record, but an inspection
# on it must never count towards a per-unit gate, and it must never be wired into
# GATING_TEMPLATES or Item.custom_produced_qc_template. Matched by code so a renamed template
# is still caught.
NON_BLOCKING_TEMPLATE_CODES = ("INS.046",)


# Incoming inspection is normally lot-level: a sample is enough to accept a purchased lot. Items listed
# here are the exception - every unit received must be inspected, exactly like the production gates.
#
# MDI200058 (Flat connector): the client confirmed its incoming inspection is done at 100%. That
# differs from INS.039's written text (1% sampling); their real practice wins.
#
# Do NOT widen this to incoming inspection in general. The Semi-Finished Dressing incoming check
# (INS.051) is AQL sampling per PR.016 and the client has said nothing about changing it. Add an item
# here only when the client has confirmed 100% for that specific item.
FULL_COVERAGE_INCOMING_ITEMS = frozenset({"MDI200058"})


def is_non_blocking_template(template: str | None) -> bool:
	return bool(template) and any(code in template for code in NON_BLOCKING_TEMPLATE_CODES)


def get_produced_qc_template(item_code: str) -> str | None:
	"""The 100%-control template required before this item's output may be booked as produced.

	Kept on its own Item field, not the native `quality_inspection_template`: that one pre-fills
	incoming inspections, and an item that is bought as well as made (e.g. the flat connector)
	needs a different template for each path.
	"""
	template = frappe.db.get_value("Item", item_code, "custom_produced_qc_template")
	if template and template not in GATING_TEMPLATES:
		frappe.throw(
			_("Item {0}: template {1} is not a 100%-control gating template.").format(
				frappe.bold(item_code), frappe.bold(template)
			)
		)
	return template or None


def row_batches(row, qty) -> list[tuple[str | None, float]]:
	"""[(batch_no, qty in stock UOM)] for one document row.

	A row that picked several batches carries them in a Serial and Batch Bundle and leaves its own
	batch_no empty, so the bundle is read when there is one. A row filled through the plain Batch No
	field (Stock Settings "use_serial_batch_fields") gets its bundle only in on_submit - after these
	before_submit gates - so then the row's batch_no is used. A non-batch item gives [(None, qty)],
	which is exactly the item-level behaviour from before batches existed.
	"""
	bundle = row.get("serial_and_batch_bundle")
	if bundle:
		per_batch = {}
		for e in frappe.get_all("Serial and Batch Entry", filters={"parent": bundle}, fields=["batch_no", "qty"]):
			per_batch[e.batch_no or None] = per_batch.get(e.batch_no or None, 0) + abs(flt(e.qty))
		if per_batch:
			return list(per_batch.items())
	return [(row.get("batch_no") or None, flt(qty))]


def row_entries(row, qty, context: str, **extra) -> list[dict]:
	"""assert_inspected entries for one row: one entry per batch, so every batch needs its own inspection."""
	return [
		{"idx": row.idx, "item_code": row.item_code, "batch_no": batch_no, "qty": batch_qty, "context": context, **extra}
		for batch_no, batch_qty in row_batches(row, qty)
	]


def build_produced_entries(rows, qty_of, context: str) -> list[dict]:
	"""assert_inspected entries for the rows whose item carries a produced-output template.

	Shared by every document that books a stage's output (a Manufacture Stock Entry, a
	Subcontracting Receipt): `qty_of(row)` gives the row's quantity in stock UOM.
	"""
	entries = []
	for row in rows:
		template = get_produced_qc_template(row.item_code)
		if template:
			entries += row_entries(row, qty_of(row), context, template=template)
	return entries


def get_accepted_inspections(
	reference_type: str,
	reference_name: str,
	item_code: str,
	batch_no: str | None = None,
	inspection_type: str | None = None,
	template: str | None = None,
	statuses: tuple[str, ...] = ("Accepted",),
) -> list:
	filters = {
		"reference_type": reference_type,
		"reference_name": reference_name,
		"item_code": item_code,
		"status": ["in", list(statuses)],
		"docstatus": 1,
	}
	if batch_no:
		filters["batch_no"] = batch_no
	if inspection_type:
		filters["inspection_type"] = inspection_type
	if template:
		filters["quality_inspection_template"] = template

	inspections = frappe.get_all(
		"Quality Inspection", filters=filters, fields=["name", "sample_size", "quality_inspection_template"]
	)
	return [qi for qi in inspections if not is_non_blocking_template(qi.quality_inspection_template)]


def assert_inspected(doc, entries: list[dict], *, inspection_type: str, full_coverage: bool = True):
	"""Block submission unless each entry is backed by an Accepted Quality Inspection on `doc`.

	entries: dicts with idx, item_code, qty (stock UOM), context (why it is gated) and optionally
	batch_no, template (a specific template the inspection must use) and statuses (the QI statuses
	that satisfy this entry; defaults to ("Accepted",) - pass ("Accepted", "Rejected") for a row
	whose purpose is routing already-inspected material, e.g. rejected stock moving to Quarantine,
	where a completed Rejected inspection is the expected, sufficient outcome).

	full_coverage=True is the per-unit rule: the inspections' Sample Size must add up to the full
	quantity, so a spot check can't release a whole row. Pass False only for lot-level checks
	(incoming goods), where sampling is the accepted practice.

	Batch-tracked items: entries come per batch (see row_entries), and only an inspection recorded
	for that same batch counts - coverage and sampling are then per batch/lot. An inspection without
	a batch never releases a batch.
	"""
	required = {}
	for entry in entries:
		statuses = tuple(entry.get("statuses") or ("Accepted",))
		key = (entry["item_code"], entry.get("batch_no"), entry.get("template"), statuses)
		if key in required:
			required[key]["qty"] += flt(entry["qty"])
		else:
			required[key] = {**entry, "qty": flt(entry["qty"]), "statuses": statuses}

	for (item_code, batch_no, template, statuses), entry in required.items():
		inspections = get_accepted_inspections(
			doc.doctype, doc.name, item_code, batch_no, inspection_type, template, statuses
		)
		item_label = frappe.bold(item_code) + (_(" (batch {0})").format(frappe.bold(batch_no)) if batch_no else "")

		if not inspections:
			frappe.throw(
				_(
					"Row #{0}: Item {1} {2}. Record a {3} {4} Quality Inspection{5} referencing this {6}, then submit again."
				).format(
					entry["idx"],
					item_label,
					entry["context"],
					_(" or ").join(statuses),
					inspection_type,
					_(' using the "{0}" template').format(template) if template else "",
					doc.doctype,
				)
			)

		covered = sum(flt(qi.sample_size) for qi in inspections)
		if full_coverage and covered < entry["qty"]:
			frappe.throw(
				_(
					"Row #{0}: Item {1} {2}. The Accepted Quality Inspection(s) cover {3:g} of {4:g} units - every unit must be inspected. Set the Sample Size to the full quantity."
				).format(entry["idx"], item_label, entry["context"], covered, entry["qty"])
			)
