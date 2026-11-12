"""One-off: the client's ERPNext users (from "List of users (Not finalized).xlsx"), with minimal roles.

Roles follow what each person does in THIS system, checked against ERPNext's own permissions:
	Quality Inspection (create/submit) ... Quality Manager only - ERPNext has no "Quality User" role for it
	Purchase Order ........................ Purchase User / Purchase Manager
	Work Order, Production Plan .......... Manufacturing User
	Delivery Note ......................... Stock User / Stock Manager, Delivery User / Delivery Manager, Sales User
	Purchase Receipt ...................... Stock User / Stock Manager, Purchase User
	Stock Entry ........................... Stock User / Stock Manager, Manufacturing User / Manager
	Job Card, BOM ......................... Manufacturing User / Manager
	Batch created by hand (supplier lot) .. Item Manager (batches made by transactions need no extra role)
	Stock Reconciliation (stock count) .... Stock Manager only
	Stock / lot reports (Stock Balance, Batch-Wise Balance History, Serial and Batch Summary) ... Stock User

OPTIONAL roles (listed per person) depend on answers from the client and are only added when passed
explicitly in extra_roles. Existing users: roles are only ADDED, never removed; a disabled user is
reported, not re-enabled. No welcome emails are sent (set first passwords with
`bench --site <site> set-password <email>`).

The User doctype queues a background job on save, so the bench (Redis) must be running - also for the
dry run. NOT wired into hooks.py or patches.txt. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.client_users_setup.run

for a DRY RUN that prints the role table and what would happen (then rolls back), and
	--kwargs "{'dry_run': False}"
to apply. Confirmed optional roles, e.g.:
	--kwargs "{'dry_run': False, 'extra_roles': {'afshin.rostami@sunmedic.se': ['Quality Manager']}}"
One person only: add 'only': ['philip.gremlin@sunmedic.se']. Safe to run twice.
"""

import frappe
from frappe.utils import validate_email_address

from medic_customizations.medic_customizations.lagerkoll.admin_user_setup import ADMIN_ROLES

MARKER = "Client users setup"

# role -> why this person needs it (shown in the confirmation table)
WHY = {
	"Manufacturing Manager": "BOMs, Job Cards, Cost of Poor Quality report; manages production",
	"Manufacturing User": "Work Orders, Production Plans, Job Cards, manufacture/transfer Stock Entries, Pick Lists",
	"Quality Manager": "create/submit Quality Inspections - the QC gates block without them",
	"Stock User": "stock + lot reports; Purchase Receipts, Delivery Notes, Stock Entries, Material Requests",
	"Delivery User": "Delivery Trips / shipment follow-up (Delivery Notes come with Stock User)",
	"Item Manager": "item barcodes / GTIN (UDI-DI), Batch records (lot numbers) created by hand",
	"Purchase User": "Purchase Orders and Subcontracting Orders (sterilization)",
	"Stock Manager": "Stock Reconciliation (stock counts) and stock settings",
}

USERS = [
	{
		"email": "philip.gremlin@sunmedic.se", "first_name": "Philip", "last_name": "Gremlin", "function": "Production Manager",
		"roles": ["Manufacturing Manager", "Manufacturing User", "Quality Manager", "Stock User"],
		"optional": {},
	},
	{
		"email": "afshin.rostami@sunmedic.se", "first_name": "Afshin", "last_name": "Rostami", "function": "Logistics",
		"roles": ["Stock User", "Delivery User"],
		"optional": {
			"Quality Manager": "if Afshin records the incoming inspections (a receipt can't be submitted without one)",
			"Stock Manager": "if Afshin does the stock counts (Stock Reconciliation)",
		},
	},
	{
		"email": "tony.johansson@sunmedic.se", "first_name": "Tony", "last_name": "Johansson", "function": "UDI, Label preparation",
		"roles": ["Manufacturing User", "Item Manager", "Stock User"],
		"optional": {},
	},
	{
		"email": "kateryna.shapovalova@sunmedic.se", "first_name": "Kateryna", "last_name": "Shapovalova", "function": "Production Planning",
		"roles": ["Manufacturing User", "Stock User"],
		"optional": {
			"Purchase User": "if planning also places Purchase / Subcontracting Orders - nobody else on the list buys",
		},
	},
	{
		"email": "abbas.karladani@sunmedic.se", "first_name": "Abbas", "last_name": "Karladani", "function": "Admin",
		"roles": list(ADMIN_ROLES),
		"optional": {},
	},
]


def role_table(extra_roles: dict | None = None) -> list[str]:
	extra_roles = extra_roles or {}
	lines = []
	for u in USERS:
		lines.append(f"{u['first_name']} {u['last_name']} <{u['email']}> - {u['function']}")
		if u["function"] == "Admin":
			lines.append(f"      {len(u['roles'])} roles, the same set as admin_user_setup (System Manager + every module's manager/user roles)")
		else:
			for role in u["roles"]:
				lines.append(f"      {role:22s} {WHY.get(role, '')}")
		for role, cond in u["optional"].items():
			on = role in extra_roles.get(u["email"], [])
			lines.append(f"      {'+' if on else '?'} {role:20s} {'ADDED (passed in extra_roles)' if on else 'optional - ' + cond}")
	return lines


def ensure_user(u: dict, roles: list[str]) -> list[tuple]:
	email = validate_email_address(u["email"].strip().lower(), throw=True)
	changes = []
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		changes.append((email, "exists"))
		if not user.enabled:
			changes.append((email, "DISABLED - left disabled"))
	else:
		user = frappe.get_doc({
			"doctype": "User", "email": email, "first_name": u["first_name"], "last_name": u["last_name"],
			"user_type": "System User", "enabled": 1, "send_welcome_email": 0,
		}).insert()
		changes.append((email, f"created ({user.full_name})"))

	missing_on_site = [r for r in roles if not frappe.db.exists("Role", r)]
	wanted = [r for r in roles if r not in missing_on_site]
	added = [r for r in wanted if r not in {d.role for d in user.roles}]
	if added:
		user.add_roles(*added)
		user.add_comment("Info", f"{MARKER}: {u['function']} - roles added: {', '.join(added)}.")
		changes.append((email, f"roles added: {', '.join(added)}"))
	else:
		changes.append((email, "roles already complete"))
	if missing_on_site:
		changes.append((email, f"roles not on this site, skipped: {missing_on_site}"))
	return changes


def apply(extra_roles: dict | None = None, only: list[str] | None = None) -> list[tuple]:
	extra_roles = extra_roles or {}
	known = {u["email"] for u in USERS}
	unknown = (set(extra_roles) | set(only or [])) - known
	if unknown:
		frappe.throw(f"Not on the client's list: {sorted(unknown)}")
	changes = []
	for u in USERS:
		if only and u["email"] not in only:
			continue
		bad = [r for r in extra_roles.get(u["email"], []) if r not in u["optional"]]
		if bad:
			frappe.throw(f"{u['email']}: {bad} are not among the optional roles {list(u['optional'])} - add them to the table first")
		changes += ensure_user(u, u["roles"] + list(extra_roles.get(u["email"], [])))
	return changes


def run(dry_run: bool = True, extra_roles: dict | None = None, only: list[str] | None = None):
	print("== Role table (confirm before applying)")
	for line in role_table(extra_roles):
		print("   " + line)
	changes = apply(extra_roles, only)
	frappe.db.rollback() if dry_run else frappe.db.commit()
	print("\n== What " + ("would happen" if dry_run else "happened"))
	for email, what in changes:
		print(f"   {email}: {what}")
	print({"dry_run": dry_run})
	return changes
