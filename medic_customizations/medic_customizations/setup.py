import frappe
from frappe import _
from frappe.utils import flt

from medic_customizations.medic_customizations.quality_control.inspection import (
	DRESSING_FINAL_CONTROL,
	FC_DRESSING_ASSEMBLY_CHECK,
	FLAT_CONNECTOR_QC,
	PRE_STERILIZATION_CHECK_DRESSING,
	PRE_STERILIZATION_CHECK_VIVAFOAM,
	PUMP_FINAL_CONTROL,
	PUMP_PRE_ASSEMBLY_CHECK,
	VIVAFOAM_FINAL_CONTROL,
)

INCOMING_INSPECTION = "Incoming Inspection"

# Warehouses flagged "QC Required On Exit" (see quality_control/warehouse_gate.py).
# Incoming Inspection holds bought goods awaiting release; Clean Room (dressing + VivaFoam) and
# ESD Area (pump assembly/programming) are the two controlled production areas.
QC_GATED_WAREHOUSES = {INCOMING_INSPECTION, "Clean Room", "ESD Area"}

# Failed incoming QC goes here. Flagged as a rejected warehouse so it is excluded from normal
# availability and can be picked as a Purchase Receipt's Rejected Warehouse.
REJECTED_WAREHOUSES = {"Quarantine"}

WAREHOUSES = [
	INCOMING_INSPECTION,
	"Released Materials",
	"Quarantine",
	"ESD Area",
	"Clean Room",
	"Packaging",
	"Finished Goods",
]

# Warehouses renamed to the client's terminology. Renamed in place (not recreated) so the stock,
# ledger history and every existing link carry over.
RENAMED_WAREHOUSES = {
	"Internal Warehouse": "Released Materials",
	"Pump Assembly": "ESD Area",
}

def _item_codes(prefix: str, first: int, last: int) -> list[str]:
	return [f"{prefix}{n}" for n in range(first, last + 1)]


# Gating template -> the output items of that stage. Each mapping comes from the Scope table
# (Product Ref column) of the instruction the template belongs to.
CHECKPOINT_ITEMS = {
	# Install PCBA output: the single consolidated pump check (INS.036, steps 1-4). The earlier
	# steps (soldering, mechanical assembly, battery connector) are deliberately not gated.
	PUMP_PRE_ASSEMBLY_CHECK: ["MDI100045"],
	# Container Sealing output (INS.010): VivereX / VivereX+ unit, fully packaged and sealed.
	PUMP_FINAL_CONTROL: ["PDI600100", "PDI600400"],
	# Internally made flat connector. The purchased path is inspected on receipt (INS.039) instead.
	FLAT_CONNECTOR_QC: ["MDI200058"],
	# FC Dressing Assembly output, made in the Clean Room: unpacked dressing per size.
	FC_DRESSING_ASSEMBLY_CHECK: _item_codes("MDI", 200086, 200093),
	# Pouched, unsterilized dressing leaving the Clean Room to be shipped to the external sterilizer
	# (INS.031): MDI200094-MDI200100 plus MDI200109 (10x20).
	PRE_STERILIZATION_CHECK_DRESSING: [*_item_codes("MDI", 200094, 200100), "MDI200109"],
	# Pouched, unsterilized VivaFoam leaving for the sterilizer (INS.041). Tracked under its own
	# item codes, separate from the sterile PDI600301-PDI600305 (batch tracking is off, so there is
	# no lot status to tell them apart): filler + pouch + sealing, made in-house like the dressings.
	PRE_STERILIZATION_CHECK_VIVAFOAM: ["MDI200021", "MDI200025", "MDI200035", "MDI200036", "MDI200037"],
	# Finished, sterilized dressing per size.
	DRESSING_FINAL_CONTROL: _item_codes("PDI", 600221, 600228),
	# Finished VivaFoam filler per size.
	VIVAFOAM_FINAL_CONTROL: _item_codes("PDI", 600301, 600305),
}

# Item -> the 100%-control template needed before its output is booked as produced. Written to
# Item.custom_produced_qc_template only where that is still empty, so later edits made in the UI
# are not overwritten.
PRODUCED_QC_TEMPLATES = {
	item_code: template for template, item_codes in CHECKPOINT_ITEMS.items() for item_code in item_codes
}


def rename_legacy_warehouses(abbr):
	for old, new in RENAMED_WAREHOUSES.items():
		old_name, new_name = f"{old} - {abbr}", f"{new} - {abbr}"
		if not frappe.db.exists("Warehouse", old_name):
			continue

		if frappe.db.exists("Warehouse", new_name):
			# Merging would silently combine two warehouses' stock - leave that to a person.
			frappe.log_error(
				title="Warehouse rename skipped",
				message=f"Both {old_name} and {new_name} exist; merge them manually.",
			)
			continue

		frappe.rename_doc("Warehouse", old_name, new_name, force=True)
		# rename_doc changes the record name only; keep warehouse_name in step with it.
		frappe.db.set_value("Warehouse", new_name, "warehouse_name", new)


def create_warehouses():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		return

	abbr = frappe.get_cached_value("Company", company, "abbr")
	parent_warehouse = f"All Warehouses - {abbr}"
	if not frappe.db.exists("Warehouse", parent_warehouse):
		parent_warehouse = None

	rename_legacy_warehouses(abbr)

	for warehouse_name in WAREHOUSES:
		full_name = f"{warehouse_name} - {abbr}"
		if frappe.db.exists("Warehouse", full_name):
			warehouse = frappe.get_doc("Warehouse", full_name)
		else:
			warehouse = frappe.new_doc("Warehouse")
			warehouse.warehouse_name = warehouse_name
			warehouse.company = company
			if parent_warehouse:
				warehouse.parent_warehouse = parent_warehouse

		warehouse.custom_qc_required_on_exit = 1 if warehouse_name in QC_GATED_WAREHOUSES else 0
		warehouse.is_rejected_warehouse = 1 if warehouse_name in REJECTED_WAREHOUSES else 0
		warehouse.save()


# The pre-sterilization checkpoints' own inspection tables: two checks each, every unit. These are
# pass/fail checks, so they are non-numeric: the inspector types the acceptance value ("Yes") as
# the reading, anything else is rejected by ERPNext's own status calculation.
LABEL_CHECK = (
	"LOT, sterilization date and expiry label readable",
	"LOT number, sterilization date and expiry date on the label are readable.",
)

PRE_STERILIZATION_CHECKS = {
	PRE_STERILIZATION_CHECK_DRESSING: [
		(
			"Dressing, extension tube and adhesive strips present",
			"Visual check that the dressing, the extension tube and the adhesive strips are all present in the pouch.",
		),
		LABEL_CHECK,
	],
	PRE_STERILIZATION_CHECK_VIVAFOAM: [
		(
			"Pouch and VivaFoam free of visible damage",
			"Visual check that the pouch and the VivaFoam inside it are not damaged.",
		),
		LABEL_CHECK,
	],
}


def create_pre_sterilization_templates():
	"""Create the INS.031 and INS.041 templates. The other gating templates were created outside this app."""
	for template, checks in PRE_STERILIZATION_CHECKS.items():
		if frappe.db.exists("Quality Inspection Template", template):
			continue

		for parameter, description in checks:
			if not frappe.db.exists("Quality Inspection Parameter", parameter):
				frappe.get_doc(
					{"doctype": "Quality Inspection Parameter", "parameter": parameter, "description": description}
				).insert()

		frappe.get_doc(
			{
				"doctype": "Quality Inspection Template",
				"quality_inspection_template_name": template,
				"item_quality_inspection_parameter": [
					{"specification": parameter, "numeric": 0, "value": "Yes"} for parameter, _description in checks
				],
			}
		).insert()


# The client confirmed that Flat Connector incoming inspection is done at 100%, not the 1% sampling that
# INS.039's written text specifies. The criteria text stored on the template rows says so; correct it
# in place, matching only the literal wording so anything the client edits later is left alone.
FLAT_CONNECTOR_INCOMING_TEMPLATE = "Incoming Control - Flat Connector (INS.039)"


def set_flat_connector_incoming_criteria():
	for row in frappe.get_all(
		"Item Quality Inspection Parameter",
		filters={"parent": FLAT_CONNECTOR_INCOMING_TEMPLATE, "specification": ["like", "%1% sampling%"]},
		fields=["name", "specification"],
	):
		frappe.db.set_value(
			"Item Quality Inspection Parameter",
			row.name,
			"specification",
			row.specification.replace("1% sampling", "100% inspection"),
			update_modified=False,
		)


# Sterilization is done by an external supplier, so the sterile items are made through native
# Subcontracting: Subcontracting Order (service item below) -> "Send to Subcontractor" Stock Entry
# with the unsterilized item -> Subcontracting Receipt when the sterile item comes back.
STERILIZATION_SERVICE_ITEM = "MDI300001"
STERILIZED_TEMPLATES = (DRESSING_FINAL_CONTROL, VIVAFOAM_FINAL_CONTROL)


# DEFAULT ASSUMPTION, not measured data: sterilization is a processing step, so one unsterilized
# unit goes in and one sterile unit comes out (1:1). The imported Lagerkoll BOMs carried a
# placeholder of 10 per sterile unit, which is wrong. If SunMedic knows the actual yield loss at
# their sterilizer (some units damaged or rejected in the cycle), set the real quantity on the
# BOM instead - 1:1 is only the correct baseline while that data is missing. A row is corrected
# only while it still holds the placeholder value, so a ratio the client sets later is never
# overwritten by a migrate.
STERILIZATION_RATIO = 1
STERILIZATION_PLACEHOLDER_QTY = 10


def correct_sterilization_bom_ratio(bom_name: str) -> bool:
	"""Replace the placeholder quantity on a sterile item's BOM with the 1:1 default.

	The BOM is already submitted, so the rows are corrected directly instead of cancel/amend:
	cancelling would break the links from the item's default BOM, the Subcontracting BOM and the
	21 BOMs that consume the item. Every rate is left as it is - ERPNext's own Update Cost would
	re-price the whole BOM from current valuation rates - and only what depends on the quantity is
	recomputed: the row's amounts, the BOM totals and the exploded raw-material list (rebuilt by
	ERPNext from the child BOMs' stored explosions, which re-prices nothing).
	"""
	bom = frappe.get_doc("BOM", bom_name)
	rows = [row for row in bom.items if flt(row.qty) == STERILIZATION_PLACEHOLDER_QTY]
	if not rows:
		return False

	for row in rows:
		row.qty = STERILIZATION_RATIO
		row.stock_qty = flt(row.qty) * flt(row.conversion_factor or 1)
		row.qty_consumed_per_unit = flt(row.stock_qty) / flt(bom.quantity)
		row.amount = flt(row.rate) * flt(row.qty)
		row.base_amount = flt(row.amount) * flt(bom.conversion_rate)
		row.db_update()

	bom.raw_material_cost = sum(flt(row.amount) for row in bom.items)
	bom.base_raw_material_cost = sum(flt(row.base_amount) for row in bom.items)
	bom.total_cost = flt(bom.operating_cost) + bom.raw_material_cost - flt(bom.scrap_material_cost)
	bom.base_total_cost = (
		flt(bom.base_operating_cost) + bom.base_raw_material_cost - flt(bom.base_scrap_material_cost)
	)
	bom.update_exploded_items()
	bom.db_update()

	bom.add_comment(
		"Info",
		_(
			"Quantities of {0} corrected from the placeholder {1} to {2} per sterile unit (default 1:1 "
			"assumption; adjust for the sterilizer's yield loss if it is known)."
		).format(", ".join(row.item_code for row in rows), STERILIZATION_PLACEHOLDER_QTY, STERILIZATION_RATIO),
	)
	return True


def setup_sterilization_subcontracting():
	"""Flag the sterile items as sub-contracted and give each a Subcontracting BOM.

	Reuses the existing default BOM of each item (unsterilized item + the sterilization service).
	The service row is flagged "Sourced by Supplier": otherwise ERPNext would ask us to supply the
	service itself to the sterilizer as if it were a raw material, and the send-out fails because
	it is not a stock item. The flag is set directly in the database because the BOMs are already
	submitted; it changes no structure. The quantities are corrected to the 1:1 default (see
	correct_sterilization_bom_ratio). The supplier itself, and the supplier warehouse on the
	Purchase Order, are chosen by the client and are not created here.
	"""
	if not frappe.db.exists("Item", STERILIZATION_SERVICE_ITEM):
		return

	service_uom = frappe.db.get_value("Item", STERILIZATION_SERVICE_ITEM, "stock_uom")

	for template in STERILIZED_TEMPLATES:
		for item_code in CHECKPOINT_ITEMS[template]:
			item = frappe.db.get_value("Item", item_code, ["default_bom", "stock_uom"], as_dict=True)
			if not item or not item.default_bom:
				continue

			frappe.db.set_value("Item", item_code, "is_sub_contracted_item", 1)
			for child_table in ("BOM Item", "BOM Explosion Item"):
				frappe.db.set_value(
					child_table,
					{"parent": item.default_bom, "item_code": STERILIZATION_SERVICE_ITEM},
					"sourced_by_supplier",
					1,
					update_modified=False,
				)

			correct_sterilization_bom_ratio(item.default_bom)

			if frappe.db.exists("Subcontracting BOM", {"finished_good": item_code, "is_active": 1}):
				continue

			frappe.get_doc(
				{
					"doctype": "Subcontracting BOM",
					"is_active": 1,
					"finished_good": item_code,
					"finished_good_qty": 1,
					"finished_good_uom": item.stock_uom,
					"finished_good_bom": item.default_bom,
					"service_item": STERILIZATION_SERVICE_ITEM,
					"service_item_qty": 1,
					"service_item_uom": service_uom,
				}
			).insert()


def set_produced_qc_templates():
	for item_code, template in PRODUCED_QC_TEMPLATES.items():
		if not (
			frappe.db.exists("Item", item_code) and frappe.db.exists("Quality Inspection Template", template)
		):
			continue

		if not frappe.db.get_value("Item", item_code, "custom_produced_qc_template"):
			frappe.db.set_value("Item", item_code, "custom_produced_qc_template", template)
