# Placeholder for the Lagerkoll -> ERPNext data migration (proposal Section 2.7).
# Blocked on the client's real Lagerkoll exports (items/articles, stock balances,
# suppliers, customers). Do not wire these into hooks.py or patches.txt - each is
# meant to be run once, manually, via `bench execute`, after the export files and
# column mapping have been confirmed against the actual client data.
#
# Where the export maps cleanly onto ERPNext's own columns, prefer the built-in
# Data Import tool (Data Import doctype) over writing custom parsing code here.
# Only implement functions below if the export needs cleaning/logic Data Import
# can't express (e.g. batch/warehouse derivation, unit conversion).


def import_items(file_path: str):
	raise NotImplementedError("Pending real Lagerkoll item/article export.")


def import_suppliers(file_path: str):
	raise NotImplementedError("Pending real Lagerkoll supplier export.")


def import_customers(file_path: str):
	raise NotImplementedError("Pending real Lagerkoll customer export.")


def import_stock_balances(file_path: str):
	raise NotImplementedError("Pending real Lagerkoll stock balance export.")
