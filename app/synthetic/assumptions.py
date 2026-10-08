"""Assumptions that shape the synthetic year of identity operations.

These are invented numbers chosen to create realistic, explainable patterns.
They are documented in docs/data-generation.md; change them there too.
"""

from datetime import date

DEFAULT_SEED = 42

SIMULATION_START = date(2025, 10, 1)
SIMULATION_END = date(2026, 9, 30)

# Employees already employed when the simulated year begins.
INITIAL_HEADCOUNT = 875
# Roughly one first-line manager per this many individual contributors.
REPORTS_PER_MANAGER = 12

# --- Hiring -----------------------------------------------------------------
# Planned hires per (year, month), excluding interns. Peaks: January-February
# (new budget year) and June-July (summer production ramp-up). December is quiet.
MONTHLY_HIRES = {
    (2025, 10): 9, (2025, 11): 7, (2025, 12): 4,
    (2026, 1): 14, (2026, 2): 12, (2026, 3): 10,
    (2026, 4): 9, (2026, 5): 10, (2026, 6): 12,
    (2026, 7): 11, (2026, 8): 8, (2026, 9): 8,
}
# Days between HR creating the record and the employee's first day.
HIRE_LEAD_DAYS = (5, 14)
# Production hiring is weighted up during the summer ramp-up.
SUMMER_MONTHS = (6, 7)
SUMMER_PRODUCTION_WEIGHT = 1.8
PART_TIME_SHARE = 0.05

INTERN_COUNT = 18
INTERN_DEPARTMENTS = ("Production", "Engineering", "Finance")
INTERN_START = date(2026, 6, 1)
INTERN_END = date(2026, 8, 21)
INTERN_END_ENTERED_ON = date(2026, 8, 3)

# --- Terminations -------------------------------------------------------------
# Planned terminations per month, by effective date. January is high (people leave
# after year-end bonuses); December has contractor roll-offs. October 2026 is after
# the simulated year: those notices arrive in September and stay as pending offboarding.
MONTHLY_TERMINATIONS = {
    (2025, 10): 7, (2025, 11): 6, (2025, 12): 9,
    (2026, 1): 13, (2026, 2): 8, (2026, 3): 7,
    (2026, 4): 7, (2026, 5): 6, (2026, 6): 8,
    (2026, 7): 9, (2026, 8): 8, (2026, 9): 7,
    (2026, 10): 6,
}
VOLUNTARY_SHARE = 0.8
NOTICE_DAYS = (7, 21)
CONTRACTOR_TURNOVER_MULTIPLIER = 2.0
MANAGER_TURNOVER_MULTIPLIER = 0.4
MIN_TENURE_DAYS_BEFORE_TERMINATION = 30
# How long HR takes to give a departed manager's reports a new manager.
MANAGER_REASSIGN_BUSINESS_DAYS = (1, 6)

# --- Leave --------------------------------------------------------------------
MONTHLY_LEAVES = 5
LEAVE_DAYS = (14, 120)
LEAVE_ENDS_IN_TERMINATION = 0.12
MIN_TENURE_DAYS_BEFORE_LEAVE = 90

# --- Other HR changes -----------------------------------------------------------
PROMOTION_CYCLE_DATE = date(2026, 3, 2)
PROMOTION_CYCLE_SHARE = 0.08
OFF_CYCLE_PROMOTIONS_PER_MONTH = 2
TRANSFERS_PER_MONTH = 2
LOCATION_CHANGES_PER_MONTH = 2
CONTRACTOR_CONVERSIONS_PER_MONTH = 1
# Plant supervisors are reshuffled regularly when shifts are rebalanced.
SUPERVISOR_CHANGES_PER_MONTH = 10
SHIFT_DEPARTMENTS = ("Production", "Maintenance", "Quality Assurance", "Logistics")
# The Logistics -> Supply Chain merge is loaded the evening before it takes effect.
# A share of individual records is missed by the bulk update.
LOGISTICS_MERGE_LOADED_ON = date(2026, 3, 31)
LOGISTICS_MERGE_MISSED_SHARE = 0.10

# --- Sync infrastructure incidents ---------------------------------------------------
SYNC_MAX_ATTEMPTS = 3
DIRECTORY_OUTAGE_DATES = (date(2025, 11, 18), date(2026, 2, 10), date(2026, 6, 23))
MISSING_EXPORT_DATES = (date(2026, 1, 5),)
# After an HR system update, the export arrived without a required column.
MISSING_COLUMN_DATES = (date(2026, 5, 12),)
# The license pool ran short during both hiring peaks.
LICENSE_SHORTAGE_PERIODS = (
    (date(2026, 1, 19), date(2026, 2, 13)),
    (date(2026, 6, 1), date(2026, 6, 26)),
)
# Terminated employees stay in the HR export for this long.
EXPORT_TERMINATED_RETENTION_DAYS = 30

# --- Data-quality defects --------------------------------------------------------------
# Probability that a new hire record is entered with each defect.
HIRE_DEFECT_RATES = {
    "missing_manager": 0.03,
    "missing_job_title": 0.01,
    "invalid_email": 0.025,
    "missing_employee_id": 0.015,
    "invalid_location": 0.02,
    "duplicate_employee": 0.025,
}
# Missing managers cluster in Production during hiring peaks (high volume, many supervisors).
PEAK_PRODUCTION_MISSING_MANAGER_RATE = 0.12
PEAK_HIRING_MONTHS = (1, 2, 6, 7)
# Contractor records often arrive from staffing agencies without a title.
CONTRACTOR_MISSING_TITLE_RATE = 0.12
# Records still using a free-text location from an older HR system.
LEGACY_LOCATION_DEFECTS = 8
LEGACY_LOCATION_VALUE = "Dayton"
# Voluntary terminations where HR set the date but never changed the status.
STATUS_NOT_UPDATED_RATE = 0.04
# Involuntary terminations entered in a hurry without a termination date.
MISSING_TERMINATION_DATE_RATE = 0.15

DEFECT_CORRECTION_PROBABILITY = 0.65
CORRECTION_DELAY_DAYS = (2, 25)
LEGACY_CORRECTION_DELAY_DAYS = (5, 90)

# --- Workflow remediation -----------------------------------------------------------
# Probability that the service desk re-runs a failed workflow, and how soon.
WORKFLOW_RERUN_PROBABILITY = {
    "onboarding": 0.8,
    "offboarding": 0.6,
    "leave": 0.5,
    "return_from_leave": 0.8,
}
RERUN_DELAY_BUSINESS_DAYS = (1, 5)
