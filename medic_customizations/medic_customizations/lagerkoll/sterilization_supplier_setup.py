"""One-off: the external sterilizer Cetro Medical AB as a Supplier, plus its supplier warehouse.

Sterilization is subcontracted (see setup.setup_sterilization_subcontracting): Purchase Order for the
service MDI300001 -> Subcontracting Order -> "Send to Subcontractor" Stock Entry -> Subcontracting
Receipt. The unsterilized pouches sit at the sterilizer for weeks; the supplier warehouse is where
ERPNext books them while they are there, so it is visible how much stock is out for sterilization.

What it creates (per company - the default company unless one is passed):
- Supplier "Cetro Medical AB": group Services, type Company, country Sweden, the company's currency.
  Address, contact, tax id and payment terms are NOT set - the client fills them in.
- Warehouse "Sterilization - Cetro Medical AB" under All Warehouses. Not QC-gated, not a rejected
  warehouse: units leave it only on the Subcontracting Receipt, which has its own gate (INS.034/037).
- The supplier as Default Supplier of MDI300001 for the company, so a Purchase Order for the
  sterilization service pre-fills it. An existing, different default supplier is NOT overwritten.

ERPNext 15 has no supplier-level default warehouse: pick "Sterilization - Cetro Medical AB" as the
Supplier Warehouse on each subcontracted Purchase Order / Subcontracting Order.

NOT wired into hooks.py or patches.txt, on purpose. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.sterilization_supplier_setup.run

for a DRY RUN (everything is computed, then rolled back), and pass --kwargs "{'dry_run': False}" to
apply. Everything already in place is left alone, so it is safe to run twice.
"""

import frappe

from medic_customizations.medic_customizations.setup import STERILIZATION_SERVICE_ITEM

MARKER = "Sterilization supplier setup"
SUPPLIER_NAME = "Cetro Medical AB"
SUPPLIER_GROUP = "Services"
SUPPLIER_COUNTRY = "Sweden"
WAREHOUSE_NAME = f"Sterilization - {SUPPLIER_NAME}"


def ensure_supplier(company: str, changes: list) -> str:
	existing = frappe.db.get_value("Supplier", {"supplier_name": SUPPLIER_NAME}, "name")
	if existing:
		changes.append(("supplier", existing, "exists - left as is"))
		return existing

	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": SUPPLIER_NAME,
			"supplier_group": SUPPLIER_GROUP,
			"supplier_type": "Company",
			"country": SUPPLIER_COUNTRY,
			"default_currency": frappe.get_cached_value("Company", company, "default_currency"),
		}
	).insert()
	supplier.add_comment(
		"Info",
		f"{MARKER}: created as the external sterilization subcontractor (service {STERILIZATION_SERVICE_ITEM}). "
		"Address, contact, tax id and payment terms to be filled in by the client.",
	)
	changes.append(("supplier", supplier.name, "created"))
	return supplier.name


def ensure_warehouse(company: str, changes: list) -> str:
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{WAREHOUSE_NAME} - {abbr}"
	if frappe.db.exists("Warehouse", name):
		changes.append(("warehouse", name, "exists - left as is"))
		return name

	parent = f"All Warehouses - {abbr}"
	warehouse = frappe.get_doc(
		{
			"doctype": "Warehouse",
			"warehouse_name": WAREHOUSE_NAME,
			"company": company,
			"parent_warehouse": parent if frappe.db.exists("Warehouse", parent) else None,
			"custom_qc_required_on_exit": 0,
			"is_rejected_warehouse": 0,
		}
	).insert()
	warehouse.add_comment(
		"Info",
		f"{MARKER}: supplier warehouse of {SUPPLIER_NAME} - unsterilized units out for sterilization. "
		"Select it as Supplier Warehouse on subcontracted Purchase Orders / Subcontracting Orders.",
	)
	changes.append(("warehouse", warehouse.name, "created"))
	return warehouse.name


def ensure_service_default_supplier(company: str, supplier: str, changes: list):
	if not frappe.db.exists("Item", STERILIZATION_SERVICE_ITEM):
		changes.append(("item default", STERILIZATION_SERVICE_ITEM, "item missing - skipped"))
		return

	item = frappe.get_doc("Item", STERILIZATION_SERVICE_ITEM)
	row = next((d for d in item.item_defaults if d.company == company), None)
	current = row.default_supplier if row else None
	if current == supplier:
		changes.append(("item default", STERILIZATION_SERVICE_ITEM, "already set - left as is"))
		return
	if current:
		changes.append(("item default", STERILIZATION_SERVICE_ITEM, f"has default supplier {current} - NOT overwritten"))
		return

	if row:
		row.default_supplier = supplier
	else:
		item.append("item_defaults", {"company": company, "default_supplier": supplier})
	item.save()
	item.add_comment("Info", f"{MARKER}: default supplier for {company} set to {supplier}.")
	changes.append(("item default", STERILIZATION_SERVICE_ITEM, f"default supplier set to {supplier}"))


def apply(company: str | None = None) -> dict:
	"""The change itself, without commit or rollback (run() decides)."""
	company = company or frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw("No company given and no default company set.")

	changes = []
	supplier = ensure_supplier(company, changes)
	warehouse = ensure_warehouse(company, changes)
	ensure_service_default_supplier(company, supplier, changes)
	return {"company": company, "supplier": supplier, "warehouse": warehouse, "changes": changes}


def run(dry_run: bool = True, company: str | None = None):
	frappe.db.sql("set session innodb_lock_wait_timeout = 15")
	result = apply(company)
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for change in result["changes"]:
		print("  ", *change)
	print({k: v for k, v in result.items() if k != "changes"})
	return result
