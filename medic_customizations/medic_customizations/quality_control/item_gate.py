import frappe
from frappe import _

from medic_customizations.medic_customizations.quality_control.inspection import GATING_TEMPLATES


def validate_produced_qc_template(doc, method=None):
	"""Only 100%-control templates may gate an item's output; see GATING_TEMPLATES in inspection.py."""
	template = doc.get("custom_produced_qc_template")
	if template and template not in GATING_TEMPLATES:
		frappe.throw(
			_(
				"{0} cannot be used as the Produced-Output QC Template: only 100%-control templates can gate every unit. Sampling-based tests (e.g. INS.046) must stay separate, non-blocking lot-level records."
			).format(frappe.bold(template))
		)
