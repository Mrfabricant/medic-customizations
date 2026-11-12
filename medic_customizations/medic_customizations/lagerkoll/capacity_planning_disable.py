"""One-off: turn off capacity planning in Manufacturing Settings so Work Orders can be submitted.

Why: since bom_operations_attach.py, Work Order submission creates Job Cards and, with capacity
planning on, schedules each operation back to back on its workstation (production capacity 1). The
workstations have no working hours, so ERPNext schedules around the clock; the submit fails with
"Unable to find the time slot in the next 30 days for the operation ..." once the operations of one
Work Order, plus any open Job Cards already booked on the same workstation, run past
capacity_planning_for_days. With the PLACEHOLDER 5 min per unit that is ~8,640 units for a single
operation, ~2,160 for the four-operation PDI600100 order - and it shrinks as open Job Cards pile up.

Giving the workstations working hours would make it worse, not better: fewer schedulable minutes
per day means the 30-day window fills sooner. The schedule would also be fiction while operation
times and shifts are placeholders. So scheduling is switched off until the client supplies real
times and shifts. ERPNext reads this flag in one place only (WorkOrder.create_job_card): Job Cards
are still created per operation, just without scheduled time slots; time logging, the overlap check
on logged time and the QC gates are unaffected.

NOT wired into hooks.py or patches.txt, on purpose: a manual, one-time settings change. Run

	bench --site <site> execute medic_customizations.medic_customizations.lagerkoll.capacity_planning_disable.run

for a DRY RUN (everything is computed, then rolled back), and pass --kwargs "{'dry_run': False}" to
apply. Already disabled -> nothing is changed, so it is safe to run twice. To revert, untick Disable
Capacity Planning in Manufacturing Settings.
"""

import frappe

SETTINGS = "Manufacturing Settings"
MARKER = "Capacity planning disable"


def run(dry_run: bool = True):
	settings = frappe.get_single(SETTINGS)
	before = settings.disable_capacity_planning
	changed = not before

	if changed:
		settings.disable_capacity_planning = 1
		settings.save()
		settings.add_comment(
			"Info",
			f"{MARKER}: Disable Capacity Planning set to 1. Operation times are PLACEHOLDERS and the "
			"workstations have no working hours, so Work Order submission failed with 'Unable to find "
			"the time slot'. Re-enable once real operation times and shifts are known.",
		)

	summary = {
		"dry_run": dry_run,
		"disable_capacity_planning_before": before,
		"disable_capacity_planning_after": settings.disable_capacity_planning,
		"changed": changed,
	}
	frappe.db.rollback() if dry_run else frappe.db.commit()
	print(summary)
	return summary
