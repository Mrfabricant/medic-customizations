# Temporary manual test for Production Plan -> Material Request / Work Order generation.
# Run via: bench --site medic.localhost execute medic_customizations.medic_customizations._production_plan_test.run
# Delete this file after use.

import json

import frappe
from frappe.utils import add_days, nowdate

COMPANY = "Medical Manufacturing Company"
ABBR = "MMC"
FG_ITEM = "PDI605225"
BOM_NO = "BOM-PDI605225-001"
SHORTAGE_COMPONENT = "MDI200128"  # only 17 in stock, ordering 20x FG needs 20
CUSTOMER = "QC Gate Test Customer 3"


def wh(name):
	return f"{name} - {ABBR}"


def run():
	frappe.set_user("Administrator")
	results = []
	created = {"customers": [], "sales_orders": [], "production_plans": [], "material_requests": [], "work_orders": []}

	if not frappe.db.exists("Customer", CUSTOMER):
		customer = frappe.new_doc("Customer")
		customer.customer_name = CUSTOMER
		customer.customer_group = frappe.db.get_value("Customer Group", {}, "name") or "All Customer Groups"
		customer.territory = frappe.db.get_value("Territory", {}, "name") or "All Territories"
		customer.insert()
		created["customers"].append(customer.name)

	so = frappe.new_doc("Sales Order")
	so.customer = CUSTOMER
	so.company = COMPANY
	so.delivery_date = add_days(nowdate(), 14)
	row = so.append("items", {})
	row.item_code = FG_ITEM
	row.qty = 20
	row.uom = "Nos"
	row.stock_uom = "Nos"
	row.conversion_factor = 1
	row.rate = 50
	row.delivery_date = add_days(nowdate(), 14)
	so.insert()
	so.submit()
	created["sales_orders"].append(so.name)
	results.append(["Sales Order submitted (qty 20, exceeds component stock)", "PASS", so.name])

	pp = frappe.new_doc("Production Plan")
	pp.company = COMPANY
	pp.get_items_from = "Sales Order"
	po_row = pp.append("sales_orders", {})
	po_row.sales_order = so.name
	po_row.sales_order_date = so.transaction_date
	po_row.customer = so.customer
	po_row.grand_total = so.grand_total
	pp.get_so_items()
	pp.insert()

	from erpnext.manufacturing.doctype.production_plan.production_plan import (
		get_items_for_material_requests,
	)

	mr_item_rows = get_items_for_material_requests(pp.as_dict())
	for row in mr_item_rows:
		pp.append("mr_items", row)

	pp.save()
	pp.submit()
	created["production_plans"].append(pp.name)
	results.append(["Production Plan submitted", "PASS", pp.name])

	before_mrs = set(frappe.get_all("Material Request", pluck="name"))
	pp.submit_material_request = 1
	pp.make_material_request()
	after_mrs = set(frappe.get_all("Material Request", pluck="name"))
	mr_names = list(after_mrs - before_mrs)
	created["material_requests"].extend(mr_names)

	if mr_names:
		shortage_found = frappe.db.exists(
			"Material Request Item", {"parent": ("in", mr_names), "item_code": SHORTAGE_COMPONENT}
		)
		results.append([
			f"Material Request raised for shortage component {SHORTAGE_COMPONENT}",
			"PASS" if shortage_found else "FAIL",
			f"MRs: {mr_names}",
		])
	else:
		results.append(["Material Request raised for shortage", "FAIL", "no Material Request created at all"])

	wo_list = pp.make_work_order()
	wo_names = []
	for doc in wo_list:
		wo = frappe.get_doc(doc) if isinstance(doc, dict) else doc
		wo.use_multi_level_bom = 0
		wo.wip_warehouse = wh("Packaging")
		wo.fg_warehouse = wh("Finished Goods")
		wo.insert()
		wo.submit()
		wo_names.append(wo.name)
		created["work_orders"].append(wo.name)

	results.append(["Work Order(s) generated from Production Plan", "PASS" if wo_names else "FAIL", str(wo_names)])

	frappe.db.commit()

	print("RESULTS_JSON_START")
	print(json.dumps({"results": results, "created": created}))
	print("RESULTS_JSON_END")

	return results


def cleanup():
	frappe.set_user("Administrator")
	log = []

	def cancel_and_delete(doctype, name):
		try:
			doc = frappe.get_doc(doctype, name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			log.append(f"removed {doctype} {name}")
		except Exception as e:
			log.append(f"FAILED to remove {doctype} {name}: {e}")

	wo_names = frappe.get_all("Work Order", filters={"production_item": FG_ITEM, "sales_order": ("like", "SAL-ORD%")}, pluck="name")
	for n in wo_names:
		cancel_and_delete("Work Order", n)

	so_names = frappe.get_all("Sales Order", filters={"customer": CUSTOMER}, pluck="name")

	mr_names = frappe.get_all("Material Request Item", filters={"item_code": SHORTAGE_COMPONENT}, pluck="parent", distinct=True)
	mr_names = [n for n in mr_names if frappe.db.get_value("Material Request", n, "owner") == "Administrator"]
	for n in mr_names:
		cancel_and_delete("Material Request", n)

	pp_names = frappe.get_all("Production Plan", filters={"company": COMPANY}, order_by="creation desc", limit_page_length=5, pluck="name")
	for n in pp_names:
		pp_so = frappe.get_all("Production Plan Sales Order", filters={"parent": n, "sales_order": ("in", so_names or [""])}, pluck="parent")
		if pp_so:
			cancel_and_delete("Production Plan", n)

	for n in so_names:
		cancel_and_delete("Sales Order", n)

	if frappe.db.exists("Customer", CUSTOMER):
		cancel_and_delete("Customer", CUSTOMER)

	frappe.db.commit()

	print("CLEANUP_JSON_START")
	print(json.dumps(log))
	print("CLEANUP_JSON_END")

	return log
