import json

import frappe

DASHBOARD_NAME = "Production & Sales Overview"

# All of these are ERPNext's own standard Dashboard Charts / Number Cards (module dashboards:
# Manufacturing, Selling, Accounts, Stock) - reused as-is, not custom report development.
CARDS = [
	"Monthly Total Work Order",
	"Monthly Completed Work Order",
	"Ongoing Job Card",
	"Monthly Quality Inspection",
	"Sales Orders to Deliver",
	"Sales Orders to Bill",
	"Annual Sales",
	"Total Outgoing Bills",
	"Total Stock Value",
	"Active Customers",
]

MATERIAL_CONSUMPTION_CHART = "Material Consumption (Manufacturing)"

CHARTS = [
	"Work Order Analysis",
	"Work Order Qty Analysis",
	"Pending Work Order",
	"Completed Operation",
	"Job Card Analysis",
	"Quality Inspection Analysis",
	"Sales Order Analysis",
	"Sales Order Trends",
	"Delivery Trends",
	"Accounts Receivable Ageing",
	"Item Shortage Summary",
	"Profit and Loss",
	MATERIAL_CONSUMPTION_CHART,
]


def create_material_consumption_chart():
	"""Standard Frappe 'Sum' Dashboard Chart on the standard Stock Entry doctype - not a custom report."""
	if frappe.db.exists("Dashboard Chart", MATERIAL_CONSUMPTION_CHART):
		return

	chart = frappe.new_doc("Dashboard Chart")
	chart.chart_name = MATERIAL_CONSUMPTION_CHART
	chart.chart_type = "Sum"
	chart.document_type = "Stock Entry"
	chart.based_on = "posting_date"
	chart.value_based_on = "total_outgoing_value"
	chart.timespan = "Last Year"
	chart.time_interval = "Monthly"
	chart.timeseries = 1
	chart.type = "Bar"
	chart.is_public = 1
	chart.filters_json = json.dumps(
		[
			["Stock Entry", "docstatus", "=", 1],
			["Stock Entry", "stock_entry_type", "=", "Manufacture"],
		]
	)
	chart.insert()


def create_company_dashboard():
	create_material_consumption_chart()

	existing_cards = set(frappe.db.get_all("Number Card", pluck="name"))
	existing_charts = set(frappe.db.get_all("Dashboard Chart", pluck="name"))

	if frappe.db.exists("Dashboard", DASHBOARD_NAME):
		dashboard = frappe.get_doc("Dashboard", DASHBOARD_NAME)
	else:
		dashboard = frappe.new_doc("Dashboard")
		dashboard.dashboard_name = DASHBOARD_NAME

	dashboard.set("cards", [])
	for card in CARDS:
		if card in existing_cards:
			dashboard.append("cards", {"card": card})

	dashboard.set("charts", [])
	for chart in CHARTS:
		if chart in existing_charts:
			dashboard.append("charts", {"chart": chart, "width": "Half"})

	dashboard.save()
