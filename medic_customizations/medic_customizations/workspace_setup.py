import json

import frappe

WORKSPACE_NAME = "Medic Operations"

SHORTCUTS = [
	{"label": "Purchase Order", "type": "DocType", "link_to": "Purchase Order", "icon": "buying"},
	{"label": "Purchase Receipt", "type": "DocType", "link_to": "Purchase Receipt", "icon": "buying"},
	{"label": "Quality Inspection", "type": "DocType", "link_to": "Quality Inspection", "icon": "quality"},
	{"label": "Stock Entry", "type": "DocType", "link_to": "Stock Entry", "icon": "stock"},
	{"label": "Work Order", "type": "DocType", "link_to": "Work Order", "icon": "tool"},
	{"label": "Job Card", "type": "DocType", "link_to": "Job Card", "icon": "kanban"},
	{"label": "Sales Order", "type": "DocType", "link_to": "Sales Order", "icon": "sell"},
	{"label": "Delivery Note", "type": "DocType", "link_to": "Delivery Note", "icon": "list-alt"},
	{"label": "Sales Invoice", "type": "DocType", "link_to": "Sales Invoice", "icon": "income"},
	{"label": "Production & Sales Overview", "type": "Dashboard", "link_to": "Production & Sales Overview", "icon": "dashboard"},
]

# Each card is (card_label, card_icon, [(link_label, link_type, link_to), ...])
CARDS = [
	(
		"Purchasing & Incoming",
		"buying",
		[
			("Supplier", "DocType", "Supplier"),
			("Purchase Order", "DocType", "Purchase Order"),
			("Purchase Receipt", "DocType", "Purchase Receipt"),
			("Quality Inspection", "DocType", "Quality Inspection"),
		],
	),
	(
		"Manufacturing",
		"tool",
		[
			("BOM", "DocType", "BOM"),
			("Production Plan", "DocType", "Production Plan"),
			("Work Order", "DocType", "Work Order"),
			("Job Card", "DocType", "Job Card"),
			("Material Request", "DocType", "Material Request"),
		],
	),
	(
		"Sales & Outgoing",
		"sell",
		[
			("Customer", "DocType", "Customer"),
			("Sales Order", "DocType", "Sales Order"),
			("Delivery Note", "DocType", "Delivery Note"),
			("Packing Slip", "DocType", "Packing Slip"),
			("Sales Invoice", "DocType", "Sales Invoice"),
		],
	),
	(
		"Stock & Masters",
		"stock",
		[
			("Item", "DocType", "Item"),
			("Item Group", "DocType", "Item Group"),
			("Warehouse", "DocType", "Warehouse"),
			("Stock Entry", "DocType", "Stock Entry"),
		],
	),
	(
		"Production Reports",
		"chart",
		[
			("Work Order Summary", "Report", "Work Order Summary"),
			("Production Analytics", "Report", "Production Analytics"),
			("Production Planning Report", "Report", "Production Planning Report"),
			("Item Shortage Report", "Report", "Item Shortage Report"),
			("Cost of Poor Quality Report", "Report", "Cost of Poor Quality Report"),
			("Quality Inspection Summary", "Report", "Quality Inspection Summary"),
		],
	),
	(
		"Sales & Financial Reports",
		"accounting",
		[
			("Sales Analytics", "Report", "Sales Analytics"),
			("Sales Order Analysis", "Report", "Sales Order Analysis"),
			("Delivered Items To Be Billed", "Report", "Delivered Items To Be Billed"),
			("Gross Profit", "Report", "Gross Profit"),
			("Accounts Receivable", "Report", "Accounts Receivable"),
			("Accounts Receivable Summary", "Report", "Accounts Receivable Summary"),
		],
	),
]


def header_block(text):
	return {"id": frappe.generate_hash(length=10), "type": "header", "data": {"text": f"<span class=\"h4\"><b>{text}</b></span>", "col": 12}}


def spacer_block():
	return {"id": frappe.generate_hash(length=10), "type": "spacer", "data": {"col": 12}}


def shortcut_block(label, col=3):
	return {"id": frappe.generate_hash(length=10), "type": "shortcut", "data": {"shortcut_name": label, "col": col}}


def card_block(card_name, col=4):
	return {"id": frappe.generate_hash(length=10), "type": "card", "data": {"card_name": card_name, "col": col}}


def build_content():
	blocks = [header_block("Quick Access")]
	blocks += [shortcut_block(s["label"]) for s in SHORTCUTS]
	blocks.append(spacer_block())
	blocks.append(header_block("Modules"))
	blocks += [card_block(name, col=3) for name, _, _ in CARDS[:4]]
	blocks.append(spacer_block())
	blocks.append(header_block("Reports"))
	blocks += [card_block(name, col=6) for name, _, _ in CARDS[4:]]
	return json.dumps(blocks)


def build_links():
	links = []
	for card_name, card_icon, items in CARDS:
		links.append({"type": "Card Break", "label": card_name, "icon": card_icon, "link_count": len(items)})
		for label, link_type, link_to in items:
			links.append(
				{
					"type": "Link",
					"label": label,
					"link_type": link_type,
					"link_to": link_to,
					"is_query_report": 1 if link_type == "Report" else 0,
				}
			)
	return links


def create_operations_workspace():
	if frappe.db.exists("Workspace", WORKSPACE_NAME):
		workspace = frappe.get_doc("Workspace", WORKSPACE_NAME)
	else:
		workspace = frappe.new_doc("Workspace")
		workspace.name = WORKSPACE_NAME
		workspace.title = WORKSPACE_NAME
		workspace.label = WORKSPACE_NAME
		workspace.public = 1
		workspace.module = "Medic Customizations"
		workspace.icon = "organization"
		workspace.sequence_id = 0.5

	workspace.content = build_content()

	workspace.set("shortcuts", [])
	for s in SHORTCUTS:
		workspace.append(
			"shortcuts",
			{
				"label": s["label"],
				"type": s["type"],
				"link_to": s["link_to"],
				"icon": s["icon"],
				"doc_view": "List" if s["type"] == "DocType" else None,
			},
		)

	workspace.set("links", [])
	for link in build_links():
		workspace.append("links", link)

	workspace.save()
