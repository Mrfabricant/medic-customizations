from frappe import _
from frappe.utils import flt

from medic_customizations.medic_customizations.quality_control.inspection import (
	assert_inspected,
	build_produced_entries,
)


def validate_subcontracting_receipt_qc_gate(doc, method=None):
	"""A subcontractor's returned output is a production event, like a Manufacture Stock Entry.

	Sterilization is external: the unsterilized pouches are sent to the sterilization supplier
	(Subcontracting Order + "Send to Subcontractor" Stock Entry) and the sterile item comes back
	on a Subcontracting Receipt weeks later. That receipt is where the returned item's checkpoint
	(Dressing Final Control INS.034 / VivaFoam Final Control INS.037) is enforced.

	Only accepted units count: rejected units go to the rejected warehouse and never enter
	stock, so they need no clearance here. The inspection is an Incoming one, matching how
	ERPNext creates a Quality Inspection from a Subcontracting Receipt.
	"""
	if doc.get("is_return"):
		return

	entries = build_produced_entries(
		[row for row in doc.items if not row.get("is_scrap_item")],
		lambda row: flt(row.qty) * flt(row.conversion_factor or 1),
		_("cannot be received back without a passed final inspection"),
	)
	assert_inspected(doc, entries, inspection_type="Incoming")
