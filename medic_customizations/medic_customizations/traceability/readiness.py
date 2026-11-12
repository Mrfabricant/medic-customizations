"""Phase 0 (read-only): how much stands between this site and batch tracking.

ERPNext refuses to tick "Has Batch No" on an item that has submitted transactions
(Item.cant_change / _get_linked_submitted_documents). This counts exactly those transactions, per
item group, so the cut-over effort on a site can be judged before anything is changed.

READ-ONLY: the database session is switched to READ ONLY first, so any write would fail; nothing is
changed. Optionally writes a per-item CSV (a file on the server, not the database) for the client's
scope review (plan question Q1). Run

	bench --site <site> execute medic_customizations.medic_customizations.traceability.readiness.run

	bench --site <site> execute medic_customizations.medic_customizations.traceability.readiness.run \\
		--kwargs "{'csv_path': '/home/frappe/traceability_scope.csv'}"
"""

import csv

import frappe

from medic_customizations.medic_customizations.traceability.lot_naming import lot_suffix

# The doctypes ERPNext checks before letting Has Batch No change (docstatus 1, by item_code).
BLOCKING_LINES = (
	"Delivery Note Item",
	"Purchase Receipt Item",
	"Stock Entry Detail",
	"Stock Reconciliation Item",
	"POS Invoice Item",
)


def _blocking(item_codes) -> dict[str, dict[str, int]]:
	"""{item_code: {doctype: number of submitted documents}} for every blocking transaction."""
	out = {}
	for dt in BLOCKING_LINES:
		for item_code, docs in frappe.db.sql(
			f"select item_code, count(distinct parent) from `tab{dt}` where docstatus=1 group by item_code"
		):
			out.setdefault(item_code, {})[dt.replace(" Item", "").replace(" Detail", "")] = docs
	# Sales / Purchase Invoices block only when they moved stock - ERPNext checks the stock ledger
	for item_code, vtype, docs in frappe.db.sql(
		"""select item_code, voucher_type, count(distinct voucher_no) from `tabStock Ledger Entry`
		where is_cancelled=0 and voucher_type in ('Sales Invoice','Purchase Invoice') group by item_code, voucher_type"""
	):
		out.setdefault(item_code, {})[vtype] = docs
	return {k: v for k, v in out.items() if k in item_codes}


def _suggested_scope(item) -> str:
	if not item.is_stock_item:
		return "not a stock item - no lots"
	if item.name.startswith("PDI"):
		return "lot (finished product)"
	if item.own_bom:
		return "lot (made in-house)"
	if item.item_group == "Consumable":
		return "CLIENT TO DECIDE (consumable)"
	return "lot (purchased)"


def run(csv_path: str | None = None):
	frappe.db.rollback()
	frappe.db.sql("SET SESSION TRANSACTION READ ONLY")
	try:
		items = frappe.db.sql(
			"""select i.name, i.item_name, i.item_group, i.is_stock_item, i.disabled, i.has_batch_no, i.has_serial_no,
			i.has_expiry_date, i.shelf_life_in_days,
			(select count(*) from tabBOM b where b.item=i.name and b.docstatus=1 and b.is_active=1) as own_bom,
			(select ifnull(sum(actual_qty),0) from tabBin where item_code=i.name) as stock_qty
			from tabItem i order by i.item_group, i.name""",
			as_dict=True,
		)
		blocking = _blocking({i.name for i in items})

		groups = {}
		for i in items:
			g = groups.setdefault(
				i.item_group, {"items": 0, "stock_items": 0, "blocked": 0, "with_stock": 0, "has_batch_no": 0, "docs": {}}
			)
			g["items"] += 1
			g["stock_items"] += i.is_stock_item
			g["has_batch_no"] += i.has_batch_no
			g["with_stock"] += 1 if i.stock_qty else 0
			if i.name in blocking:
				g["blocked"] += 1
				for dt, n in blocking[i.name].items():
					g["docs"][dt] = g["docs"].get(dt, 0) + n

		vouchers = frappe.db.sql(
			"""select voucher_type, count(distinct voucher_no), count(distinct item_code) from `tabStock Ledger Entry`
			where is_cancelled=0 group by voucher_type order by 2 desc"""
		)
		totals = {
			"site": frappe.local.site,
			"items": len(items),
			"items_blocked_from_batch_tracking": len(blocking),
			"batches": frappe.db.count("Batch"),
			"serial_nos": frappe.db.count("Serial No"),
			"serial_and_batch_bundles": frappe.db.count("Serial and Batch Bundle"),
		}

		print("\n== Totals")
		for k, v in totals.items():
			print(f"   {k}: {v}")
		print("\n== Per item group  (items | stock items | already batch | with stock | BLOCKED | blocking docs by type)")
		for name, g in groups.items():
			docs = ", ".join(f"{dt} {n}" for dt, n in sorted(g["docs"].items())) or "-"
			print(f"   {name}: {g['items']} | {g['stock_items']} | {g['has_batch_no']} | {g['with_stock']} | {g['blocked']} | {docs}")
		print("\n== Submitted stock transactions by voucher type  (documents | distinct items)")
		for vtype, docs, n_items in vouchers:
			print(f"   {vtype}: {docs} | {n_items}")

		if csv_path:
			with open(csv_path, "w", newline="") as f:
				w = csv.writer(f)
				w.writerow(["item_code", "item_name", "item_group", "is_stock_item", "disabled", "made_in_house",
					"stock_qty", "has_batch_no", "has_expiry_date", "shelf_life_in_days", "blocked_by",
					"suggested_scope", "lot_suffix", "client_decision"])
				for i in items:
					try:
						suffix = lot_suffix(i.name)
					except Exception:
						suffix = "?"
					w.writerow([i.name, i.item_name, i.item_group, i.is_stock_item, i.disabled, 1 if i.own_bom else 0,
						i.stock_qty, i.has_batch_no, i.has_expiry_date, i.shelf_life_in_days or "",
						"; ".join(f"{dt} x{n}" for dt, n in sorted(blocking.get(i.name, {}).items())),
						_suggested_scope(i), suffix, ""])
			print(f"\n   per-item CSV written to {csv_path}")
		return {"totals": totals, "groups": groups}
	finally:
		frappe.db.rollback()
