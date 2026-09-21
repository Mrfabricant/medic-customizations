import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import (
	assert_inspected,
	build_produced_entries,
	get_produced_qc_template,
)
from medic_customizations.medic_customizations.setup import INCOMING_INSPECTION

# Stock Entry purposes whose source rows are raw material *consumed* by a production stage. The
# gate is output-based, so consuming an input from a controlled area is never blocked - the stage's
# own output is checked instead (see validate_produced_output).
CONSUMPTION_PURPOSES = (
	"Manufacture",
	"Material Consumption for Manufacture",
	"Material Transfer for Manufacture",
)


def get_qc_gated_warehouses() -> dict[str, str]:
	"""{warehouse name: warehouse_name without company suffix} for every warehouse flagged QC Required On Exit."""
	return {
		w.name: w.warehouse_name
		for w in frappe.get_all(
			"Warehouse", filters={"custom_qc_required_on_exit": 1}, fields=["name", "warehouse_name"]
		)
	}


def validate_stock_entry_qc_gate(doc, method=None):
	validate_produced_output(doc)
	validate_controlled_area_exit(doc)


def validate_produced_output(doc):
	"""Output-based gate: a stage's output can't be booked as produced until every unit passed QC.

	Fires only on a Manufacture entry's finished-item rows, so it is event-based: stock that
	entered through a Purchase Receipt (e.g. a bought flat connector, already inspected on
	receipt) never triggers a produced-output requirement, and no sourcing flag is needed.

	Which items are checkpoints, and which 100% template each needs, comes from
	Item.custom_produced_qc_template. The pump chain has ONE consolidated checkpoint (INS.036,
	after Install PCBA) - only that item carries a template, the earlier steps (soldering,
	mechanical assembly, battery connector) are deliberately not gated on their own.
	Job Card completion is not gated yet: no BOM has operations, so no Job Cards exist.
	"""
	if doc.purpose != "Manufacture":
		return

	entries = build_produced_entries(
		[row for row in doc.items if row.is_finished_item],
		lambda row: row.transfer_qty,
		_("cannot be booked as produced"),
	)
	assert_inspected(doc, entries, inspection_type="In Process")


def validate_controlled_area_exit(doc):
	"""Stock leaving a QC-flagged warehouse needs the inspection that is relevant to that area.

	- Incoming Inspection holds bought goods: an Incoming inspection, lot-level (sampling is the
	  accepted practice there).
	- Clean Room / ESD Area hold produced WIP: an In Process inspection covering every unit.
	  Raw material consumed by a work order is skipped, and so are checkpoint items - their
	  output was already inspected 100% when it was booked, so a second inspection here would
	  just duplicate the consolidated checkpoint.
	"""
	gated = get_qc_gated_warehouses()
	if not gated:
		return

	incoming, in_process = [], []
	for row in doc.items:
		warehouse_name = gated.get(row.s_warehouse)
		if warehouse_name is None:
			continue

		entry = {
			"idx": row.idx,
			"item_code": row.item_code,
			"batch_no": row.get("batch_no"),
			"qty": row.transfer_qty,
			"context": _("cannot leave warehouse {0}").format(frappe.bold(row.s_warehouse)),
		}

		if warehouse_name == INCOMING_INSPECTION:
			incoming.append(entry)
		elif doc.purpose not in CONSUMPTION_PURPOSES and not get_produced_qc_template(row.item_code):
			in_process.append(entry)

	assert_inspected(doc, incoming, inspection_type="Incoming", full_coverage=False)
	assert_inspected(doc, in_process, inspection_type="In Process")
