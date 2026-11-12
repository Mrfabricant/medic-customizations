"""One-off: a client administrator user (Parisa Karladani) with full desk access.

"Admin" here means the System Manager role (settings, users, customization) plus the manager and
user roles of every module this ERP uses, so she can also work in and approve all documents. Frappe's
own "Administrator" role is reserved for the built-in Administrator account and is NOT given.

Existing user (matched by email): roles are only ADDED, never removed; a disabled user is reported,
not re-enabled. Nothing else on an existing user is changed.

The email address is required - there is no default. No welcome email is sent unless asked for: no
outgoing Email Account is configured on medic.localhost, so it would not arrive. Set the first
password with `bench --site <site> set-password <email>` instead (it prompts for the password).

NOT wired into hooks.py or patches.txt, on purpose. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.admin_user_setup.run \\
		--kwargs "{'email': 'parisa@...'}"

for a DRY RUN (everything is computed, then rolled back), and add 'dry_run': False to apply. Optional
kwargs: first_name, last_name, send_welcome_email (default False). Safe to run twice.
"""

import frappe
from frappe.utils import validate_email_address

MARKER = "Admin user setup"

ADMIN_ROLES = (
	"System Manager",
	"Accounts Manager",
	"Accounts User",
	"Auditor",
	"Dashboard Manager",
	"Delivery Manager",
	"Delivery User",
	"Item Manager",
	"Manufacturing Manager",
	"Manufacturing User",
	"Prepared Report User",
	"Purchase Manager",
	"Purchase Master Manager",
	"Purchase User",
	"Quality Manager",
	"Report Manager",
	"Sales Manager",
	"Sales Master Manager",
	"Sales User",
	"Stock Manager",
	"Stock User",
	"Workspace Manager",
)


def apply(email: str, first_name: str = "Parisa", last_name: str = "Karladani", send_welcome_email: bool = False) -> dict:
	"""The change itself, without commit or rollback (run() decides)."""
	email = validate_email_address((email or "").strip().lower(), throw=True)
	missing_roles = [r for r in ADMIN_ROLES if not frappe.db.exists("Role", r)]
	roles = [r for r in ADMIN_ROLES if r not in missing_roles]
	changes = []

	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
		changes.append(("user", email, "exists"))
		if not user.enabled:
			changes.append(("user", email, "is DISABLED - left disabled, enable it by hand if intended"))
	else:
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"last_name": last_name,
				"user_type": "System User",
				"enabled": 1,
				"send_welcome_email": 1 if send_welcome_email else 0,
			}
		).insert()
		changes.append(("user", email, f"created ({user.full_name})"))

	added = [r for r in roles if r not in {d.role for d in user.roles}]
	if added:
		user.add_roles(*added)  # saves the user
		user.add_comment("Info", f"{MARKER}: roles added - {', '.join(added)}.")
		changes.append(("roles", email, f"added {len(added)}: {', '.join(added)}"))
	else:
		changes.append(("roles", email, "all admin roles already present"))

	return {"user": email, "changes": changes, "missing_roles": missing_roles}


def run(email: str | None = None, dry_run: bool = True, first_name: str = "Parisa", last_name: str = "Karladani", send_welcome_email: bool = False):
	if not email:
		frappe.throw("Pass the user's email: --kwargs \"{'email': '...'}\"")
	result = apply(email, first_name, last_name, send_welcome_email)
	result["dry_run"] = dry_run
	frappe.db.rollback() if dry_run else frappe.db.commit()
	for change in result["changes"]:
		print("  ", *change)
	if result["missing_roles"]:
		print("   roles not on this site, skipped:", result["missing_roles"])
	print({"user": result["user"], "dry_run": dry_run})
	return result
