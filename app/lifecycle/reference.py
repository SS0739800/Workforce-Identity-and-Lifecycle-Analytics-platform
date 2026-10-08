"""Reference data for the fictional organisation, Northstar Manufacturing.

Everything here is invented. Group, role and license names are generic so the
project does not imply any real directory, tenant or product configuration.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

# ---------------------------------------------------------------------------
# Allowed values (also enforced as CHECK constraints in the database)
# ---------------------------------------------------------------------------

EMPLOYMENT_STATUSES = ("active", "terminated")
LEAVE_STATUSES = ("none", "on_leave")
EMPLOYMENT_TYPES = ("full_time", "part_time", "intern", "contractor")
ACCOUNT_STATUSES = ("active", "disabled")
ASSIGNMENT_STATUSES = ("active", "removed")

SYNC_RUN_STATUSES = ("completed", "completed_with_errors", "failed")
SYNC_RECORD_STATUSES = ("success", "failed")

WORKFLOW_TYPES = ("onboarding", "offboarding", "leave", "return_from_leave")
WORKFLOW_STATUSES = ("pending", "in_progress", "completed", "failed")
ACTION_TYPES = (
    "create_account",
    "enable_account",
    "disable_account",
    "reset_password",
    "update_attribute",
    "add_group_membership",
    "remove_group_membership",
    "assign_role",
    "remove_role",
    "assign_license",
    "remove_license",
    "revoke_session",
)
ACTION_STATUSES = ("success", "failed", "skipped")

ERROR_TYPES = (
    "MISSING_ATTRIBUTE",
    "INVALID_ATTRIBUTE",
    "DEPENDENCY_ERROR",
    "TIMEOUT",
    "PERMISSION_ERROR",
    "ALREADY_DISABLED",
    "RESOURCE_NOT_FOUND",
    "VALIDATION_ERROR",
)

DQ_SEVERITIES = ("low", "medium", "high", "critical")
DQ_STATUSES = ("open", "resolved")

# ---------------------------------------------------------------------------
# Organisation
# ---------------------------------------------------------------------------

COMPANY_NAME = "Northstar Manufacturing"
# .example is reserved (RFC 2606), so these addresses can never belong to a real domain.
EMAIL_DOMAIN = "northstar-mfg.example"

CEO_TITLE = "Chief Executive Officer"

LOCATIONS = {
    "Dayton Plant": "DAY",
    "Greenville Plant": "GRV",
    "Monterrey Plant": "MTY",
    "Fort Wayne Distribution Center": "FWD",
    "Chicago Office": "CHI",
    "Remote": "REM",
}

PLANTS = {"Dayton Plant": 0.45, "Greenville Plant": 0.35, "Monterrey Plant": 0.20}


@dataclass(frozen=True)
class Department:
    name: str
    code: str
    headcount_share: float
    head_title: str
    manager_title: str
    # Each ladder is a promotion path, entry level first.
    title_ladders: tuple[tuple[str, ...], ...]
    location_weights: dict[str, float]
    # Relative likelihood of an employee in this department leaving during the year.
    turnover_weight: float
    contractor_share: float
    role: str
    licenses: tuple[str, ...] = ()
    frontline: bool = False
    intern_title: str | None = None
    extra_groups: tuple[str, ...] = field(default=())


DEPARTMENTS: dict[str, Department] = {
    d.name: d
    for d in [
        Department(
            "Production", "PROD", 0.33, "Director of Production", "Production Supervisor",
            (
                ("Production Operator I", "Production Operator II", "Senior Production Operator", "Line Lead"),
                ("Machine Operator", "CNC Machinist", "Senior CNC Machinist"),
            ),
            PLANTS, turnover_weight=1.6, contractor_share=0.15,
            role="MES Line Operator", frontline=True, intern_title="Operations Intern",
        ),
        Department(
            "Maintenance", "MAINT", 0.08, "Director of Maintenance", "Maintenance Supervisor",
            (("Maintenance Technician", "Senior Maintenance Technician", "Maintenance Planner"),),
            PLANTS, turnover_weight=1.0, contractor_share=0.05,
            role="CMMS Technician", frontline=True,
        ),
        Department(
            "Quality Assurance", "QA", 0.07, "Director of Quality", "Quality Supervisor",
            (("Quality Inspector", "Senior Quality Inspector"), ("Quality Engineer", "Senior Quality Engineer")),
            PLANTS, turnover_weight=0.9, contractor_share=0.05,
            role="QMS Inspector",
        ),
        Department(
            "Engineering", "ENG", 0.10, "Director of Engineering", "Engineering Manager",
            (
                ("Manufacturing Engineer I", "Manufacturing Engineer II", "Senior Manufacturing Engineer"),
                ("Process Engineer", "Senior Process Engineer"),
            ),
            {"Dayton Plant": 0.35, "Greenville Plant": 0.20, "Chicago Office": 0.30, "Remote": 0.15},
            turnover_weight=0.8, contractor_share=0.10,
            role="PLM Engineer", licenses=("CAD Workstation",), intern_title="Engineering Intern",
            extra_groups=("VPN Users",),
        ),
        Department(
            "Supply Chain", "SCM", 0.07, "Director of Supply Chain", "Supply Chain Manager",
            (
                ("Buyer", "Senior Buyer"),
                ("Supply Chain Analyst", "Senior Supply Chain Analyst"),
                ("Production Planner", "Senior Production Planner"),
            ),
            {"Chicago Office": 0.50, "Dayton Plant": 0.25, "Fort Wayne Distribution Center": 0.25},
            turnover_weight=0.9, contractor_share=0.05,
            role="ERP Purchasing", licenses=("ERP Named User",),
        ),
        Department(
            # Merged into Supply Chain on LOGISTICS_MERGE_DATE (see valid_departments).
            "Logistics", "LOG", 0.07, "Director of Logistics", "Logistics Supervisor",
            (("Material Handler", "Forklift Operator", "Shipping Coordinator"),),
            {"Fort Wayne Distribution Center": 0.70, "Dayton Plant": 0.15, "Greenville Plant": 0.15},
            turnover_weight=1.4, contractor_share=0.20,
            role="WMS Operator", frontline=True,
        ),
        Department(
            "Sales", "SALES", 0.06, "Director of Sales", "Sales Manager",
            (("Inside Sales Representative", "Account Manager", "Senior Account Manager"),),
            {"Chicago Office": 0.50, "Remote": 0.50},
            turnover_weight=1.2, contractor_share=0.02,
            role="CRM Sales User", licenses=("CRM Seat",), extra_groups=("VPN Users",),
        ),
        Department(
            "Customer Service", "CS", 0.05, "Director of Customer Service", "Customer Service Supervisor",
            (("Customer Service Representative", "Senior Customer Service Representative"),),
            {"Chicago Office": 0.70, "Remote": 0.30},
            turnover_weight=1.5, contractor_share=0.10,
            role="CRM Service Agent", licenses=("CRM Seat",),
        ),
        Department(
            "Finance", "FIN", 0.04, "Controller", "Accounting Manager",
            (
                ("Accounts Payable Specialist", "Staff Accountant", "Senior Accountant"),
                ("Financial Analyst", "Senior Financial Analyst"),
            ),
            {"Chicago Office": 0.85, "Remote": 0.15},
            turnover_weight=0.7, contractor_share=0.03,
            role="ERP Finance User", licenses=("ERP Named User",), intern_title="Finance Intern",
        ),
        Department(
            "Human Resources", "HR", 0.03, "Director of Human Resources", "HR Manager",
            (("HR Coordinator", "HR Generalist", "HR Business Partner"),),
            {"Chicago Office": 0.80, "Dayton Plant": 0.20},
            turnover_weight=0.8, contractor_share=0.0,
            role="HRIS HR Partner",
        ),
        Department(
            "Information Technology", "IT", 0.05, "Director of IT", "IT Manager",
            (
                ("Service Desk Analyst", "Systems Administrator", "Senior Systems Administrator"),
                ("Identity and Access Analyst", "Senior Identity and Access Analyst"),
            ),
            {"Chicago Office": 0.50, "Remote": 0.30, "Dayton Plant": 0.20},
            turnover_weight=0.9, contractor_share=0.20,
            role="ITSM Agent", extra_groups=("VPN Users",),
        ),
        Department(
            "Executive", "EXEC", 0.0, CEO_TITLE, CEO_TITLE,
            (("Executive Assistant",),),
            {"Chicago Office": 1.0},
            turnover_weight=0.0, contractor_share=0.0,
            role="ERP Executive Viewer",
        ),
    ]
}

# The Logistics department was merged into Supply Chain partway through the simulated
# year. Records still showing "Logistics" after this date fail department validation.
LOGISTICS_MERGE_DATE = date(2026, 4, 1)


def valid_departments(as_of: date) -> set[str]:
    names = set(DEPARTMENTS)
    if as_of >= LOGISTICS_MERGE_DATE:
        names.discard("Logistics")
    return names


# Titles that carry a privileged directory role. Removing these at offboarding matters most.
PRIVILEGED_TITLES = {
    "Systems Administrator",
    "Senior Systems Administrator",
    "Identity and Access Analyst",
    "Senior Identity and Access Analyst",
}
PRIVILEGED_ROLE = "Directory Administrator"
MANAGER_ROLE = "Manager Self-Service Approver"


@dataclass(frozen=True)
class Entitlements:
    groups: tuple[str, ...]
    roles: tuple[str, ...]
    licenses: tuple[str, ...]


def entitlements_for(
    department: str | None,
    location: str | None,
    job_title: str | None,
    employment_type: str,
    is_manager: bool,
) -> Entitlements:
    """Birthright access an employee should hold, derived from HR attributes."""
    dept = DEPARTMENTS.get(department or "")

    groups = ["All Staff"]
    if dept:
        groups.append(f"DEPT-{dept.code}")
    if location in LOCATIONS:
        groups.append(f"SITE-{LOCATIONS[location]}")
    if location in ("Chicago Office", "Remote") or (dept and "VPN Users" in dept.extra_groups):
        groups.append("VPN Users")
    if employment_type == "contractor":
        groups.append("Contractors")
    if is_manager:
        groups.append("People Managers")

    roles = []
    if dept:
        roles.append(dept.role)
    if is_manager:
        roles.append(MANAGER_ROLE)
    if job_title in PRIVILEGED_TITLES:
        roles.append(PRIVILEGED_ROLE)

    licenses = []
    if dept and dept.frontline and not is_manager:
        licenses.append("Office Suite Frontline")
    else:
        licenses.append("Office Suite Standard")
    if dept:
        licenses.extend(dept.licenses)

    return Entitlements(tuple(dict.fromkeys(groups)), tuple(roles), tuple(licenses))


# Department heads and first-line managers are recognised by title (HR has no "is manager" flag).
MANAGER_TITLES = {d.head_title for d in DEPARTMENTS.values()} | {d.manager_title for d in DEPARTMENTS.values()}


def access_for_employee(employee: Mapping) -> Entitlements:
    """Birthright access for an HR record."""
    return entitlements_for(
        employee["department"],
        employee["location"],
        employee["job_title"],
        employee["employment_type"],
        is_manager=employee["job_title"] in MANAGER_TITLES,
    )
