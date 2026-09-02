import frappe

QC_GATED_WAREHOUSES = {"Incoming Inspection", "Packaging", "Pump Assembly", "Clean Room"}

WAREHOUSES = [
	"Incoming Inspection",
	"Internal Warehouse",
	"Packaging",
	"Pump Assembly",
	"Clean Room",
	"Finished Goods",
]


def create_warehouses():
	company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		return

	abbr = frappe.get_cached_value("Company", company, "abbr")
	parent_warehouse = f"All Warehouses - {abbr}"
	if not frappe.db.exists("Warehouse", parent_warehouse):
		parent_warehouse = None

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
		warehouse.save()
