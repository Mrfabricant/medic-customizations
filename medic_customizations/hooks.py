app_name = "medic_customizations"
app_title = "Medic Customizations"
app_publisher = "sohail zafar"
app_description = "Medical device manufacturing erp"
app_email = "sohail@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "medic_customizations",
# 		"logo": "/assets/medic_customizations/logo.png",
# 		"title": "Medic Customizations",
# 		"route": "/medic_customizations",
# 		"has_permission": "medic_customizations.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/medic_customizations/css/medic_customizations.css"
# app_include_js = "/assets/medic_customizations/js/medic_customizations.js"

# Fixtures
# ------------------
# Custom Field(s) that back the quality-control gates (see doc_events below)

fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				["Warehouse-custom_qc_required_on_exit", "Item-custom_produced_qc_template"],
			]
		],
	},
]

# include js, css files in header of web template
# web_include_css = "/assets/medic_customizations/css/medic_customizations.css"
# web_include_js = "/assets/medic_customizations/js/medic_customizations.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "medic_customizations/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "medic_customizations/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "medic_customizations.utils.jinja_methods",
# 	"filters": "medic_customizations.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "medic_customizations.install.before_install"
# after_install = "medic_customizations.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "medic_customizations.uninstall.before_uninstall"
# after_uninstall = "medic_customizations.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "medic_customizations.utils.before_app_install"
# after_app_install = "medic_customizations.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "medic_customizations.utils.before_app_uninstall"
# after_app_uninstall = "medic_customizations.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "medic_customizations.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Stock Entry": {
		"before_submit": "medic_customizations.medic_customizations.quality_control.warehouse_gate.validate_stock_entry_qc_gate"
	},
	"Delivery Note": {
		"before_submit": "medic_customizations.medic_customizations.quality_control.delivery_gate.validate_delivery_note_qc_gate"
	},
	"Sales Invoice": {
		"before_submit": "medic_customizations.medic_customizations.quality_control.sales_invoice_gate.validate_sales_invoice_qc_gate"
	},
	"Subcontracting Receipt": {
		"before_submit": "medic_customizations.medic_customizations.quality_control.subcontracting_gate.validate_subcontracting_receipt_qc_gate"
	},
	"Item": {
		"validate": "medic_customizations.medic_customizations.quality_control.item_gate.validate_produced_qc_template"
	},
}

# Migration Events
# ----------------
# Runs after fixtures are synced, so the QC Custom Fields already exist on Warehouse and Item
# by the time this seeds/updates the warehouse tree and the produced-output templates.

after_migrate = [
	"medic_customizations.medic_customizations.setup.create_warehouses",
	"medic_customizations.medic_customizations.setup.create_pre_sterilization_templates",
	"medic_customizations.medic_customizations.setup.set_flat_connector_incoming_criteria",
	"medic_customizations.medic_customizations.setup.set_produced_qc_templates",
	"medic_customizations.medic_customizations.setup.setup_sterilization_subcontracting",
	"medic_customizations.medic_customizations.dashboard_setup.create_company_dashboard",
	"medic_customizations.medic_customizations.workspace_setup.create_operations_workspace",
]

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"medic_customizations.tasks.all"
# 	],
# 	"daily": [
# 		"medic_customizations.tasks.daily"
# 	],
# 	"hourly": [
# 		"medic_customizations.tasks.hourly"
# 	],
# 	"weekly": [
# 		"medic_customizations.tasks.weekly"
# 	],
# 	"monthly": [
# 		"medic_customizations.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "medic_customizations.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "medic_customizations.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "medic_customizations.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["medic_customizations.utils.before_request"]
# after_request = ["medic_customizations.utils.after_request"]

# Job Events
# ----------
# before_job = ["medic_customizations.utils.before_job"]
# after_job = ["medic_customizations.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"medic_customizations.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

