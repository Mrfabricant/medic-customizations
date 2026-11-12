import frappe
from frappe import _

from medic_customizations.medic_customizations.setup import INCOMING_INSPECTION


def validate_receipt_into_incoming_inspection(doc, method=None):
	"""Bought stock is received into Incoming Inspection; it reaches Released Materials only through the
	exit gate there (warehouse_gate.validate_controlled_area_exit).

	Needed since items default to Released Materials (so Work Orders and planning see the stock): a
	receipt made from a planned Purchase Order would otherwise carry that warehouse and skip the QC area.
	Rejected quantities use the separate Rejected Warehouse field and are not affected. Returns and
	Purchase Invoices that don't update stock are skipped; Subcontracting Receipts have their own gate.
	"""
	if doc.get("is_return") or (doc.doctype == "Purchase Invoice" and not doc.get("update_stock")):
		return

	incoming = frappe.db.get_value("Warehouse", {"warehouse_name": INCOMING_INSPECTION, "company": doc.company}, "name")
	if not incoming:
		return

	wrong = [
		row
		for row in doc.items
		if row.get("warehouse") != incoming and frappe.get_cached_value("Item", row.item_code, "is_stock_item")
	]
	if wrong:
		frappe.throw(
			_("Bought goods are received into {0} and released after incoming inspection. Set the Accepted Warehouse to {0} on: {1}").format(
				frappe.bold(incoming),
				", ".join(_("row #{0} {1} ({2})").format(r.idx, r.item_code, r.get("warehouse") or _("no warehouse")) for r in wrong),
			),
			title=_("Receive into Incoming Inspection"),
		)
