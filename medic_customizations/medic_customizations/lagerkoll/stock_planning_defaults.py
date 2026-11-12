"""One-off: make stock visible to Work Orders and planning, and stop offering made items for purchase.

Cause: every Item Default points at "Stores" (1 unit) while the stock (904k units) sits in "Released
Materials". ERPNext takes a Work Order row's source warehouse from the item default (the Work Order
header only fills empty rows), and Production Plan projects stock in the item default when no "For
Warehouse" is chosen - so Work Orders show 0 available and planning proposes buying everything.
On top of that all items are "Purchase" items with Material Request Type "Purchase", including the
ones made here, so planning and Purchase Orders treat sets, pumps and dressings as bought goods.

What it changes (company = default company unless given; warehouse names use its abbreviation):
A. Item Default warehouse "Stores" -> "Released Materials" for stock items (where the stock is).
B. Stock Settings default warehouse "Stores" -> "Released Materials" (used for new items).
C. Items made here (active default BOM), not subcontracted: Is Purchase Item off, Default Material
   Request Type "Manufacture". Left alone: BOUGHT_AND_MADE (the flat connector is also bought) and the
   subcontracted sterile items (they are made through the purchasing side: Subcontracting Order).
D. Purchase Order / Purchase Receipt / Purchase Invoice "Set ... Warehouse" default "Incoming
   Inspection" (Property Setters), so bought goods are still received into the QC area. The receipt
   check in quality_control/receipt_gate.py enforces it for receipts made from planned orders.
Existing documents (Work Orders, receipts) are not changed - listed in the output instead.

NOT wired into hooks.py or patches.txt. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.stock_planning_defaults.run

for a DRY RUN (computed, then rolled back), and pass --kwargs "{'dry_run': False}" to apply. Anything
already in its target state is skipped, so it is safe to run twice. Clears the cache at the end.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MARKER = "Stock planning defaults"
STORES, RELEASED, INCOMING = "Stores", "Released Materials", "Incoming Inspection"
BOUGHT_AND_MADE = frozenset({"MDI200058"})  # flat connector: made in-house AND bought (client)
PURCHASE_DOCTYPES = ("Purchase Order", "Purchase Receipt", "Purchase Invoice")


def _comment(doctype, name, text):
	frappe.get_doc(doctype, name).add_comment("Info", f"{MARKER}: {text}")


def apply(company: str | None = None) -> dict:
	company = company or frappe.db.get_single_value("Global Defaults", "default_company")
	abbr = frappe.get_cached_value("Company", company, "abbr")
	stores, released, incoming = (f"{w} - {abbr}" for w in (STORES, RELEASED, INCOMING))
	for wh in (released, incoming):
		if not frappe.db.exists("Warehouse", wh):
			frappe.throw(f"Warehouse {wh} does not exist on this site - nothing changed.")
	out = {"company": company, "item_defaults": 0, "flags": [], "kept": [], "property_setters": [], "stock_settings": None}

	# A. item default warehouse
	for row in frappe.db.sql(
		"""select d.name, d.parent from `tabItem Default` d join tabItem i on i.name = d.parent
		where d.parenttype = 'Item' and d.company = %s and d.default_warehouse = %s and i.is_stock_item = 1""",
		(company, stores),
		as_dict=True,
	):
		frappe.db.set_value("Item Default", row.name, "default_warehouse", released, update_modified=False)
		_comment("Item", row.parent, f"default warehouse {stores} -> {released} (where the stock is).")
		out["item_defaults"] += 1

	# B. stock settings
	current = frappe.db.get_single_value("Stock Settings", "default_warehouse")
	if current == stores:
		frappe.db.set_single_value("Stock Settings", "default_warehouse", released)
		_comment("Stock Settings", "Stock Settings", f"default warehouse {stores} -> {released}.")
		out["stock_settings"] = f"{stores} -> {released}"
	else:
		out["stock_settings"] = f"unchanged ({current})"

	# C. items made here
	for item in frappe.db.sql(
		"""select i.name, i.is_purchase_item, i.default_material_request_type, i.is_sub_contracted_item
		from tabItem i join tabBOM b on b.name = i.default_bom and b.docstatus = 1 and b.is_active = 1
		where i.disabled = 0 order by i.name""",
		as_dict=True,
	):
		if item.name in BOUGHT_AND_MADE or item.is_sub_contracted_item:
			out["kept"].append((item.name, "bought and made" if item.name in BOUGHT_AND_MADE else "subcontracted"))
			continue
		target = {"is_purchase_item": 0, "default_material_request_type": "Manufacture"}
		changes = {k: v for k, v in target.items() if item.get(k) != v}
		if not changes:
			continue
		frappe.db.set_value("Item", item.name, changes, update_modified=False)
		_comment("Item", item.name, f"made in-house (active BOM): {changes}.")
		out["flags"].append((item.name, changes))

	# D. purchase documents receive into Incoming Inspection by default
	for dt in PURCHASE_DOCTYPES:
		existing = frappe.db.get_value(
			"Property Setter", {"doc_type": dt, "field_name": "set_warehouse", "property": "default"}, "value"
		)
		if existing == incoming:
			out["property_setters"].append((dt, "unchanged"))
			continue
		ps = make_property_setter(dt, "set_warehouse", "default", incoming, "Text", validate_fields_for_doctype=False, is_system_generated=False)
		ps.add_comment("Info", f"{MARKER}: {dt} warehouse default {existing or '(none)'} -> {incoming}.")
		out["property_setters"].append((dt, f"{existing or '(none)'} -> {incoming}"))

	out["open_work_orders_not_on_released"] = frappe.db.sql(
		"""select distinct w.name, wi.source_warehouse from `tabWork Order` w join `tabWork Order Item` wi on wi.parent = w.name
		where w.docstatus = 1 and w.status not in ('Completed', 'Closed', 'Cancelled') and wi.source_warehouse != %s""",
		released,
	)
	return out


def run(dry_run: bool = True, company: str | None = None):
	result = apply(company)
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	frappe.clear_cache()  # drop cached items/meta either way; after a rollback they rebuild from the DB
	print(f"   A. item default warehouses changed: {result['item_defaults']}")
	print(f"   B. Stock Settings default warehouse: {result['stock_settings']}")
	print(f"   C. made items changed: {len(result['flags'])}; kept as is: {result['kept']}")
	print(f"   D. purchase document defaults: {result['property_setters']}")
	for wo, wh in result["open_work_orders_not_on_released"]:
		print(f"   existing Work Order left as is: {wo} draws from {wh}")
	print({"dry_run": dry_run})
	return result
