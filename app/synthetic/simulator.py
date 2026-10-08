"""Day-by-day simulation of one year of identity operations at Northstar Manufacturing.

Each simulated day runs in the same order:

    00:05  scheduled HR status changes (terminations taking effect)
    02:00  nightly HR -> identity sync, then lifecycle workflows it detects
    07:45  manual re-run of the sync, only after a directory outage
    08:00+ business hours (weekdays): HR changes, data corrections, service-desk re-runs
    18:00  data-quality scan of every record

Nothing is generated "as a statistic". Sync failures, workflow failures and
data-quality issues all come out of the same mechanics: bad HR data blocks the sync,
failed cleanup actions leave access behind, and the scan detects what is left.
"""

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from app.lifecycle.executor import execute_plan
from app.lifecycle.reference import (
    CEO_TITLE,
    DEPARTMENTS,
    EMAIL_DOMAIN,
    Entitlements,
    access_for_employee,
    valid_departments,
)
from app.lifecycle.sync import (
    due_workflows,
    in_hr_export,
    needs_attribute_sync,
    sync_record_error,
)
from app.lifecycle.validation import AccessSnapshot, find_duplicates, find_issues, issue_changes
from app.lifecycle.workflows import (
    ASSIGNMENT_ACTIONS,
    IdentityState,
    PlannedAction,
    access_changes,
    can_rerun,
    plan_leave,
    plan_offboarding,
    plan_onboarding,
    plan_rerun,
    plan_return_from_leave,
    username_from_email,
)
from app.synthetic import assumptions as A
from app.synthetic.names import FIRST_NAMES, LAST_NAMES

TABLES = (
    "employees",
    "identity_accounts",
    "group_memberships",
    "role_assignments",
    "license_assignments",
    "sync_runs",
    "sync_record_results",
    "attribute_change_logs",
    "workflow_runs",
    "workflow_actions",
    "data_quality_issues",
    "audit_events",
)

MISSPELLED_LOCATIONS = ("Monterey Plant", "Greenville", "Ft Wayne DC")

# kind -> (table, name column, attribute on EmployeeState)
ASSIGNMENT_KINDS = {
    "group": ("group_memberships", "group_name", "groups"),
    "role": ("role_assignments", "role_name", "roles"),
    "license": ("license_assignments", "license_name", "licenses"),
}
TITLE_LADDERS = {
    title: ladder
    for dept in DEPARTMENTS.values()
    for ladder in dept.title_ladders
    for title in ladder
}


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------

def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=timezone.utc)


def is_business_day(day: date) -> bool:
    return day.weekday() < 5


def next_business_day(day: date) -> date:
    while not is_business_day(day):
        day += timedelta(days=1)
    return day


def add_business_days(day: date, count: int) -> date:
    for _ in range(count):
        day = next_business_day(day + timedelta(days=1))
    return day


def business_days_in_month(year: int, month: int) -> list[date]:
    day = date(year, month, 1)
    days = []
    while day.month == month:
        if is_business_day(day):
            days.append(day)
        day += timedelta(days=1)
    return days


def as_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# ---------------------------------------------------------------------------
# Simulation state
# ---------------------------------------------------------------------------

@dataclass
class EmployeeState:
    """In-memory state for one employee. `row` is the employees table row itself."""

    row: dict
    is_manager: bool = False
    is_head: bool = False
    is_duplicate: bool = False
    account: dict | None = None
    groups: dict[str, dict] = field(default_factory=dict)
    roles: dict[str, dict] = field(default_factory=dict)
    licenses: dict[str, dict] = field(default_factory=dict)
    # Consecutive failed sync attempts since the HR record last changed.
    sync_attempts: int = 0
    onboarding_requested: bool = False
    offboarding_run: dict | None = None
    offboarded: bool = False
    leave_applied: bool = False
    pending_termination: date | None = None

    @property
    def id(self) -> int:
        return self.row["id"]

    @property
    def active(self) -> bool:
        return self.row["employment_status"] == "active"

    def identity(self) -> IdentityState:
        return IdentityState(
            account_status=self.account["account_status"] if self.account else None,
            groups=tuple(self.groups),
            roles=tuple(self.roles),
            licenses=tuple(self.licenses),
        )


class SimulatedIdentity:
    """The executor's view of one employee's identity data held in memory."""

    def __init__(self, simulation: "Simulation", state: EmployeeState):
        self.simulation = simulation
        self.state = state

    def account_status(self) -> str | None:
        return self.state.account["account_status"] if self.state.account else None

    def apply(self, action: PlannedAction, when: datetime) -> None:
        self.simulation._apply_action(self.state, action, when)


class Simulation:
    def __init__(self, seed: int = A.DEFAULT_SEED):
        self.rng = random.Random(seed)
        self.tables: dict[str, list[dict]] = {name: [] for name in TABLES}
        self.people: dict[int, EmployeeState] = {}
        self.dept_heads: dict[str, int] = {}
        self.ceo_id: int | None = None
        self.used_email_names: set[str] = set()
        self.used_usernames: set[str] = set()
        self.next_employee_number = 1
        self.scheduled: dict[date, list[tuple[str, dict]]] = defaultdict(list)
        self.status_changes_due: dict[date, list[int]] = defaultdict(list)
        self.onboarding_queue: list[EmployeeState] = []
        self.open_issues: dict[tuple[int, str], dict] = {}
        self.handlers = {
            "hire": self._on_hire,
            "duplicate_record": self._on_duplicate_record,
            "termination": self._on_termination,
            "leave_start": self._on_leave_start,
            "leave_return": self._on_leave_return,
            "promotion": self._on_promotion,
            "promotion_cycle": self._on_promotion_cycle,
            "transfer": self._on_transfer,
            "location_change": self._on_location_change,
            "conversion": self._on_conversion,
            "supervisor_change": self._on_supervisor_change,
            "logistics_merge": self._on_logistics_merge,
            "manager_reassign": self._on_manager_reassign,
            "correction": self._on_correction,
            "workflow_rerun": self._on_workflow_rerun,
        }

    def run(self) -> dict[str, list[dict]]:
        self._build_initial_workforce()
        self._plan_year()
        day = A.SIMULATION_START
        while day <= A.SIMULATION_END:
            self._simulate_day(day)
            day += timedelta(days=1)
        return self.tables

    def _simulate_day(self, day: date) -> None:
        self._apply_due_status_changes(day)
        self._run_sync(at(day, 2), triggered_by="schedule")
        if day in A.DIRECTORY_OUTAGE_DATES:
            self._run_sync(at(day, 7, 45), triggered_by="manual")
        if is_business_day(day):
            self._run_business_hours(day)
        self._scan_data_quality(at(day, 18))

    # -- table helpers ---------------------------------------------------------

    def _add(self, table: str, values: dict) -> dict:
        rows = self.tables[table]
        row = {"id": len(rows) + 1, **values}
        rows.append(row)
        return row

    def _audit(self, state: EmployeeState, event_type: str, description: str, when: datetime, source: str) -> None:
        self._add("audit_events", {
            "employee_id": state.id,
            "event_type": event_type,
            "description": description,
            "event_timestamp": when,
            "source": source,
        })

    def _schedule(self, day: date, kind: str, payload: dict | None = None) -> None:
        self.scheduled[next_business_day(day)].append((kind, payload or {}))

    def _business_time(self, day: date) -> datetime:
        return at(day, 8) + timedelta(seconds=self.rng.randint(0, 9 * 3600 + 1800))

    # -- people ------------------------------------------------------------------

    def _new_person(self) -> tuple[str, str, str]:
        first = self.rng.choice(FIRST_NAMES)
        last = self.rng.choice(LAST_NAMES)
        base = f"{first}.{last}".lower()
        name = base
        suffix = 2
        while name in self.used_email_names:
            name = f"{base}{suffix}"
            suffix += 1
        self.used_email_names.add(name)
        return first, last, f"{name}@{EMAIL_DOMAIN}"

    def _next_employee_id(self) -> str:
        employee_id = f"EMP{self.next_employee_number:05d}"
        self.next_employee_number += 1
        return employee_id

    def _create_employee(
        self,
        department: str,
        job_title: str,
        manager_id: int | None,
        location: str,
        employment_type: str,
        hire_date: date,
        created_at: datetime,
        is_manager: bool = False,
        is_head: bool = False,
    ) -> EmployeeState:
        first, last, email = self._new_person()
        row = self._add("employees", {
            "employee_id": self._next_employee_id(),
            "first_name": first,
            "last_name": last,
            "email": email,
            "department": department,
            "job_title": job_title,
            "manager_id": manager_id,
            "location": location,
            "employment_type": employment_type,
            "hire_date": hire_date,
            "termination_date": None,
            "employment_status": "active",
            "leave_status": "none",
            "created_at": created_at,
            "updated_at": created_at,
        })
        state = EmployeeState(row=row, is_manager=is_manager, is_head=is_head)
        self.people[state.id] = state
        return state

    def _choose_location(self, department: str) -> str:
        weights = DEPARTMENTS[department].location_weights
        return self.rng.choices(list(weights), weights=list(weights.values()))[0]

    def _choose_employment_type(self, department: str) -> str:
        roll = self.rng.random()
        if roll < DEPARTMENTS[department].contractor_share:
            return "contractor"
        if roll < DEPARTMENTS[department].contractor_share + A.PART_TIME_SHARE:
            return "part_time"
        return "full_time"

    def _pick_manager(self, department: str, location: str | None, exclude: int | None = None) -> int:
        """A first-line manager in the department, preferring the same site."""
        candidates = [
            s for s in self.people.values()
            if s.is_manager and not s.is_head and s.active and not s.is_duplicate
            and s.row["department"] == department and s.id != exclude
        ]
        same_site = [s for s in candidates if s.row["location"] == location]
        pool = same_site or candidates
        if pool:
            return self.rng.choice(pool).id
        head_id = self.dept_heads.get(department)
        if head_id and self.people[head_id].active and head_id != exclude:
            return head_id
        return self.ceo_id

    def _desired_access(self, state: EmployeeState) -> Entitlements:
        return access_for_employee(state.row)

    def _change(self, state: EmployeeState, attribute: str, value, when: datetime, source: str = "hr_system") -> None:
        """Change an HR attribute and record it in attribute_change_logs."""
        row = state.row
        old = row[attribute]
        if old == value:
            return
        row[attribute] = value
        row["updated_at"] = when
        self._add("attribute_change_logs", {
            "employee_id": state.id,
            "attribute_name": attribute,
            "old_value": as_text(old),
            "new_value": as_text(value),
            "changed_at": when,
            "source": source,
        })
        # A changed record gets a fresh set of sync attempts.
        state.sync_attempts = 0

    # -- initial workforce ---------------------------------------------------------

    def _build_initial_workforce(self) -> None:
        start = A.SIMULATION_START
        rng = self.rng

        def tenure(low: int, high: int) -> date:
            return start - timedelta(days=rng.randint(low, high))

        def created(hire: date) -> datetime:
            return at(hire - timedelta(days=7), 9)

        hire = tenure(4000, 6500)
        ceo = self._create_employee(
            "Executive", CEO_TITLE, None, "Chicago Office", "full_time", hire, created(hire),
            is_manager=True, is_head=True,
        )
        self.ceo_id = ceo.id
        self.dept_heads["Executive"] = ceo.id
        for _ in range(2):
            hire = tenure(400, 3000)
            self._create_employee(
                "Executive", "Executive Assistant", ceo.id, "Chicago Office", "full_time", hire, created(hire)
            )

        departments = [d for d in DEPARTMENTS.values() if d.headcount_share > 0]
        total_share = sum(d.headcount_share for d in departments)
        remaining = A.INITIAL_HEADCOUNT - 3

        for dept in departments:
            size = round(remaining * dept.headcount_share / total_share)
            main_site = max(dept.location_weights, key=dept.location_weights.get)
            hire = tenure(3000, 7000)
            head = self._create_employee(
                dept.name, dept.head_title, ceo.id, main_site, "full_time", hire, created(hire),
                is_manager=True, is_head=True,
            )
            self.dept_heads[dept.name] = head.id

            manager_count = max(1, round((size - 1) / (A.REPORTS_PER_MANAGER + 1)))
            for _ in range(manager_count):
                hire = tenure(1500, 6000)
                self._create_employee(
                    dept.name, dept.manager_title, head.id, self._choose_location(dept.name),
                    "full_time", hire, created(hire), is_manager=True,
                )

            for _ in range(size - 1 - manager_count):
                ladder = rng.choice(dept.title_ladders)
                level = rng.choices(range(len(ladder)), weights=[4, 3, 2, 1][: len(ladder)])[0]
                location = self._choose_location(dept.name)
                # Tenure skews recent: most of a manufacturing workforce has been there a few years.
                hire = start - timedelta(days=min(30 + int(rng.expovariate(1 / 1300)), 9000))
                self._create_employee(
                    dept.name, ladder[level], self._pick_manager(dept.name, location), location,
                    self._choose_employment_type(dept.name), hire, created(hire),
                )

        for state in self.people.values():
            self._provision_existing_access(state)

        # A few records still carry a free-text location from the previous HR system.
        dayton = [s for s in self.people.values() if s.row["location"] == "Dayton Plant" and not s.is_manager]
        for state in rng.sample(dayton, A.LEGACY_LOCATION_DEFECTS):
            state.row["location"] = A.LEGACY_LOCATION_VALUE
            self._maybe_schedule_correction(
                state, "location", "Dayton Plant", A.LEGACY_LOCATION_VALUE, start, A.LEGACY_CORRECTION_DELAY_DAYS
            )

    def _provision_existing_access(self, state: EmployeeState) -> None:
        """Accounts and access for people hired before the simulated year (no workflow history)."""
        created_at = at(state.row["hire_date"], 7)
        username = state.row["email"].split("@")[0]
        self.used_usernames.add(username)
        state.account = self._add("identity_accounts", {
            "employee_id": state.id,
            "username": username,
            "account_status": "active",
            "account_created_at": created_at,
            "account_disabled_at": None,
            "last_sync_at": at(A.SIMULATION_START - timedelta(days=1), 2),
        })
        state.onboarding_requested = True
        desired = self._desired_access(state)
        for kind, names in (("group", desired.groups), ("role", desired.roles), ("license", desired.licenses)):
            for name in names:
                self._assign(state, kind, name, created_at, audit_source=None)

    # -- planning --------------------------------------------------------------------

    def _plan_year(self) -> None:
        rng = self.rng
        for (year, month), count in A.MONTHLY_HIRES.items():
            days = business_days_in_month(year, month)
            for _ in range(count):
                self._schedule(rng.choice(days), "hire")
            for _ in range(A.MONTHLY_LEAVES):
                self._schedule(rng.choice(days), "leave_start")
            for _ in range(A.OFF_CYCLE_PROMOTIONS_PER_MONTH):
                self._schedule(rng.choice(days), "promotion")
            for _ in range(A.TRANSFERS_PER_MONTH):
                self._schedule(rng.choice(days), "transfer")
            for _ in range(A.LOCATION_CHANGES_PER_MONTH):
                self._schedule(rng.choice(days), "location_change")
            for _ in range(A.CONTRACTOR_CONVERSIONS_PER_MONTH):
                self._schedule(rng.choice(days), "conversion")
            for _ in range(A.SUPERVISOR_CHANGES_PER_MONTH):
                self._schedule(rng.choice(days), "supervisor_change")

        intern_days = business_days_in_month(A.INTERN_START.year, A.INTERN_START.month - 1)
        for _ in range(A.INTERN_COUNT):
            self._schedule(rng.choice(intern_days), "hire", {"intern": True})

        for (year, month), count in A.MONTHLY_TERMINATIONS.items():
            days = business_days_in_month(year, month)
            for _ in range(count):
                effective = rng.choice(days)
                voluntary = rng.random() < A.VOLUNTARY_SHARE
                notice = effective
                if voluntary:
                    notice = effective - timedelta(days=rng.randint(*A.NOTICE_DAYS))
                if A.SIMULATION_START <= notice <= A.SIMULATION_END:
                    self._schedule(notice, "termination", {"effective": effective, "voluntary": voluntary})

        self._schedule(A.PROMOTION_CYCLE_DATE, "promotion_cycle", {"when": at(A.PROMOTION_CYCLE_DATE, 9)})
        self._schedule(
            A.LOGISTICS_MERGE_LOADED_ON, "logistics_merge", {"when": at(A.LOGISTICS_MERGE_LOADED_ON, 17, 30)}
        )

    def _maybe_schedule_correction(
        self, state: EmployeeState, attribute: str, value, bad_value, day: date,
        delay_days: tuple[int, int] = A.CORRECTION_DELAY_DAYS,
    ) -> None:
        if self.rng.random() < A.DEFECT_CORRECTION_PROBABILITY:
            fix_day = day + timedelta(days=self.rng.randint(*delay_days))
            self._schedule(fix_day, "correction", {
                "employee": state.id, "attribute": attribute, "value": value, "bad_value": bad_value,
            })

    # -- business-hours events -------------------------------------------------------

    def _run_business_hours(self, day: date) -> None:
        events = []
        for kind, payload in self.scheduled.pop(day, []):
            when = payload.get("when") or self._business_time(day)
            events.append((when, len(events), kind, payload))
        events.sort(key=lambda event: (event[0], event[1]))
        for when, _, kind, payload in events:
            self.handlers[kind](when, payload)

    def _eligible(self, state: EmployeeState) -> bool:
        """Real, active, non-executive employees with no termination in progress."""
        return (
            state.active
            and not state.is_duplicate
            and not state.is_head
            and state.pending_termination is None
            and state.row["department"] in DEPARTMENTS
            and state.row["employment_type"] != "intern"
        )

    def _on_hire(self, when: datetime, payload: dict) -> None:
        rng = self.rng
        day = when.date()
        if payload.get("intern"):
            department = rng.choice(A.INTERN_DEPARTMENTS)
            title = DEPARTMENTS[department].intern_title
            employment_type = "intern"
            hire_date = A.INTERN_START
        else:
            department = self._choose_hiring_department(day)
            title = rng.choice(DEPARTMENTS[department].title_ladders)[0]
            employment_type = self._choose_employment_type(department)
            hire_date = min(day + timedelta(days=rng.randint(*A.HIRE_LEAD_DAYS)), A.SIMULATION_END)

        location = self._choose_location(department)
        state = self._create_employee(
            department, title, self._pick_manager(department, location), location,
            employment_type, hire_date, when,
        )
        self._inject_hire_defects(state, day)
        if employment_type == "intern":
            self._schedule(A.INTERN_END_ENTERED_ON, "termination", {
                "employee": state.id, "effective": A.INTERN_END, "voluntary": True,
            })

    def _choose_hiring_department(self, day: date) -> str:
        allowed = valid_departments(day)
        names, weights = [], []
        for dept in DEPARTMENTS.values():
            if dept.name not in allowed or dept.headcount_share == 0:
                continue
            weight = dept.headcount_share
            if dept.name == "Production" and day.month in A.SUMMER_MONTHS:
                weight *= A.SUMMER_PRODUCTION_WEIGHT
            names.append(dept.name)
            weights.append(weight)
        return self.rng.choices(names, weights=weights)[0]

    def _inject_hire_defects(self, state: EmployeeState, day: date) -> None:
        """Enter some new-hire records with mistakes, as happens with manual HR data entry."""
        rng = self.rng
        row = state.row
        rates = dict(A.HIRE_DEFECT_RATES)
        if row["department"] == "Production" and day.month in A.PEAK_HIRING_MONTHS:
            rates["missing_manager"] = A.PEAK_PRODUCTION_MISSING_MANAGER_RATE
        if row["employment_type"] == "contractor":
            rates["missing_job_title"] = A.CONTRACTOR_MISSING_TITLE_RATE

        defects = []
        if rng.random() < rates["missing_manager"]:
            defects.append(("manager_id", None))
        if rng.random() < rates["missing_job_title"]:
            defects.append(("job_title", None))
        if rng.random() < rates["invalid_email"]:
            defects.append(("email", self._mangle_email(row["email"])))
        if rng.random() < rates["missing_employee_id"]:
            defects.append(("employee_id", None))
        if rng.random() < rates["invalid_location"]:
            defects.append(("location", rng.choice(MISSPELLED_LOCATIONS)))

        for attribute, bad_value in defects:
            correct_value = row[attribute]
            row[attribute] = bad_value  # entered wrong at creation, so there is no change log
            self._maybe_schedule_correction(state, attribute, correct_value, bad_value, day)

        if rng.random() < rates["duplicate_employee"]:
            self._schedule(add_business_days(day, rng.randint(1, 3)), "duplicate_record", {"employee": state.id})

    def _mangle_email(self, email: str) -> str:
        name, domain = email.split("@")
        style = self.rng.randint(1, 3)
        if style == 1:
            return f"{name}@{domain.split('.')[0]}"  # missing top-level domain
        if style == 2:
            return f"{name}.{domain}"  # missing @
        return f"{name.replace('.', ' ')}@{domain}"  # space instead of dot

    def _on_duplicate_record(self, when: datetime, payload: dict) -> None:
        """HR enters the same hire a second time under a new employee ID."""
        original = self.people[payload["employee"]].row
        values = {key: original[key] for key in original if key != "id"}
        values.update(employee_id=self._next_employee_id(), created_at=when, updated_at=when)
        row = self._add("employees", values)
        state = EmployeeState(row=row, is_duplicate=True)
        self.people[state.id] = state

    def _on_termination(self, when: datetime, payload: dict) -> None:
        effective = payload["effective"]
        if "employee" in payload:
            state = self.people[payload["employee"]]
            if not state.active or state.pending_termination is not None:
                return
        else:
            state = self._choose_leaver(when.date())
            if state is None:
                return

        state.pending_termination = effective
        if payload["voluntary"]:
            self._change(state, "termination_date", effective, when)
            if self.rng.random() < A.STATUS_NOT_UPDATED_RATE:
                # HR never flips the status, so nothing triggers offboarding until someone notices.
                fix_day = effective + timedelta(days=self.rng.randint(*A.CORRECTION_DELAY_DAYS))
                self._maybe_schedule_correction(state, "employment_status", "terminated", "active", fix_day,
                                                delay_days=(0, 0))
            else:
                self.status_changes_due[effective + timedelta(days=1)].append(state.id)
            return

        # Involuntary: effective immediately, and the service desk disables the account by hand.
        if self.rng.random() < A.MISSING_TERMINATION_DATE_RATE:
            self._maybe_schedule_correction(state, "termination_date", effective, None, when.date())
        else:
            self._change(state, "termination_date", effective, when)
        self._change(state, "employment_status", "terminated", when)
        self._after_termination(state, when)
        disable_at = when + timedelta(minutes=self.rng.randint(10, 25))
        if state.account and state.account["account_status"] == "active":
            state.account["account_status"] = "disabled"
            state.account["account_disabled_at"] = disable_at
            self._audit(state, "account_disabled", "Account disabled manually at time of termination",
                        disable_at, "service_desk")

    def _choose_leaver(self, day: date) -> EmployeeState | None:
        candidates, weights = [], []
        for state in self.people.values():
            if not self._eligible(state) or state.row["leave_status"] != "none":
                continue
            if state.row["hire_date"] > day - timedelta(days=A.MIN_TENURE_DAYS_BEFORE_TERMINATION):
                continue
            weight = DEPARTMENTS[state.row["department"]].turnover_weight
            if state.row["employment_type"] == "contractor":
                weight *= A.CONTRACTOR_TURNOVER_MULTIPLIER
            if state.is_manager:
                weight *= A.MANAGER_TURNOVER_MULTIPLIER
            candidates.append(state)
            weights.append(weight)
        if not candidates:
            return None
        return self.rng.choices(candidates, weights=weights)[0]

    def _apply_due_status_changes(self, day: date) -> None:
        """Future-dated terminations take effect just after midnight following the last working day."""
        for employee_id in self.status_changes_due.pop(day, []):
            state = self.people[employee_id]
            if state.active:
                when = at(day, 0, 5)
                self._change(state, "employment_status", "terminated", when)
                self._after_termination(state, when)

    def _after_termination(self, state: EmployeeState, when: datetime) -> None:
        if state.row["leave_status"] == "on_leave":
            self._change(state, "leave_status", "none", when)
        if not state.is_manager:
            return
        for report in self.people.values():
            if report.active and report.row["manager_id"] == state.id:
                day = add_business_days(when.date(), self.rng.randint(*A.MANAGER_REASSIGN_BUSINESS_DAYS))
                self._schedule(day, "manager_reassign", {"employee": report.id, "old_manager": state.id})

    def _on_manager_reassign(self, when: datetime, payload: dict) -> None:
        state = self.people[payload["employee"]]
        if not state.active or state.row["manager_id"] != payload["old_manager"]:
            return
        new_manager = self._pick_manager(state.row["department"], state.row["location"], exclude=payload["old_manager"])
        self._change(state, "manager_id", new_manager, when)

    def _on_leave_start(self, when: datetime, payload: dict) -> None:
        day = when.date()
        candidates = [
            s for s in self.people.values()
            if self._eligible(s) and s.row["leave_status"] == "none"
            and s.row["hire_date"] <= day - timedelta(days=A.MIN_TENURE_DAYS_BEFORE_LEAVE)
        ]
        if not candidates:
            return
        state = self.rng.choice(candidates)
        self._change(state, "leave_status", "on_leave", when)
        end = next_business_day(day + timedelta(days=self.rng.randint(*A.LEAVE_DAYS)))
        if self.rng.random() < A.LEAVE_ENDS_IN_TERMINATION:
            self._schedule(end, "termination", {"employee": state.id, "effective": end, "voluntary": False})
        else:
            self._schedule(end, "leave_return", {"employee": state.id})

    def _on_leave_return(self, when: datetime, payload: dict) -> None:
        state = self.people[payload["employee"]]
        if state.active and state.row["leave_status"] == "on_leave":
            self._change(state, "leave_status", "none", when)

    def _promotable(self) -> list[EmployeeState]:
        result = []
        for state in self.people.values():
            title = state.row["job_title"]
            ladder = TITLE_LADDERS.get(title)
            if self._eligible(state) and not state.is_manager and ladder and title != ladder[-1]:
                result.append(state)
        return result

    def _promote(self, state: EmployeeState, when: datetime) -> None:
        ladder = TITLE_LADDERS[state.row["job_title"]]
        next_title = ladder[ladder.index(state.row["job_title"]) + 1]
        self._change(state, "job_title", next_title, when)

    def _on_promotion(self, when: datetime, payload: dict) -> None:
        candidates = self._promotable()
        if candidates:
            self._promote(self.rng.choice(candidates), when)

    def _on_promotion_cycle(self, when: datetime, payload: dict) -> None:
        for state in self._promotable():
            if self.rng.random() < A.PROMOTION_CYCLE_SHARE:
                self._promote(state, when + timedelta(seconds=self.rng.randint(0, 3600)))

    def _on_transfer(self, when: datetime, payload: dict) -> None:
        candidates = [
            s for s in self.people.values()
            if self._eligible(s) and not s.is_manager and s.row["leave_status"] == "none"
        ]
        if not candidates:
            return
        state = self.rng.choice(candidates)
        options = sorted(valid_departments(when.date()) - {state.row["department"], "Executive"})
        new_department = self.rng.choice(options)
        new_title = self.rng.choice(DEPARTMENTS[new_department].title_ladders)[0]
        new_manager = self._pick_manager(new_department, state.row["location"])
        self._change(state, "department", new_department, when)
        self._change(state, "job_title", new_title, when)
        self._change(state, "manager_id", new_manager, when)

    def _on_location_change(self, when: datetime, payload: dict) -> None:
        candidates = [
            s for s in self.people.values()
            if self._eligible(s) and not s.is_manager and s.row["leave_status"] == "none"
        ]
        if not candidates:
            return
        state = self.rng.choice(candidates)
        weights = {
            name: weight
            for name, weight in DEPARTMENTS[state.row["department"]].location_weights.items()
            if name != state.row["location"]
        }
        if not weights:
            return
        new_location = self.rng.choices(list(weights), weights=list(weights.values()))[0]
        self._change(state, "location", new_location, when)
        manager = self.people.get(state.row["manager_id"])
        if manager and manager.row["location"] != new_location:
            new_manager = self._pick_manager(state.row["department"], new_location)
            self._change(state, "manager_id", new_manager, when)

    def _on_conversion(self, when: datetime, payload: dict) -> None:
        candidates = [
            s for s in self.people.values()
            if self._eligible(s) and s.row["employment_type"] == "contractor"
        ]
        if candidates:
            self._change(self.rng.choice(candidates), "employment_type", "full_time", when)

    def _on_supervisor_change(self, when: datetime, payload: dict) -> None:
        candidates = [
            s for s in self.people.values()
            if self._eligible(s) and not s.is_manager and s.row["department"] in A.SHIFT_DEPARTMENTS
        ]
        if not candidates:
            return
        state = self.rng.choice(candidates)
        current = state.row["manager_id"]
        new_manager = self._pick_manager(state.row["department"], state.row["location"], exclude=current)
        self._change(state, "manager_id", new_manager, when)

    def _on_logistics_merge(self, when: datetime, payload: dict) -> None:
        """Bulk move of Logistics into Supply Chain; a few individual records are missed."""
        supply_chain_head = self.dept_heads["Supply Chain"]
        for state in self.people.values():
            if not state.active or state.is_duplicate or state.row["department"] != "Logistics":
                continue
            if not state.is_manager and self.rng.random() < A.LOGISTICS_MERGE_MISSED_SHARE:
                self._maybe_schedule_correction(state, "department", "Supply Chain", "Logistics", when.date())
                continue
            self._change(state, "department", "Supply Chain", when)
            if state.is_head:
                self._change(state, "manager_id", supply_chain_head, when)

    def _on_correction(self, when: datetime, payload: dict) -> None:
        state = self.people[payload["employee"]]
        attribute = payload["attribute"]
        # Skip if someone already changed the value, or the person has left (except the
        # status correction itself, which is exactly the fix for a missed termination).
        if state.row[attribute] != payload["bad_value"]:
            return
        if not state.active and attribute != "termination_date":
            return

        value = payload["value"]
        if attribute == "manager_id" and not self.people[value].active:
            value = self._pick_manager(state.row["department"], state.row["location"])
        self._change(state, attribute, value, when, source="data_correction")
        if attribute == "employment_status":
            self._after_termination(state, when)

    # -- nightly sync ------------------------------------------------------------------

    def _run_sync(self, start: datetime, triggered_by: str) -> None:
        day = start.date()
        scheduled = triggered_by == "schedule"
        run = self._add("sync_runs", {
            "run_id": f"SYNC-{start:%Y%m%d-%H%M}",
            "started_at": start,
            "completed_at": None,
            "status": "completed",
            "total_records": 0,
            "successful_records": 0,
            "failed_records": 0,
            "skipped_records": 0,
            "triggered_by": triggered_by,
            "error_message": None,
        })

        # File-level checks happen before any record is read, as in the original automation.
        if scheduled and day in A.MISSING_EXPORT_DATES:
            self._fail_run(run, start, f"HR export for {day.isoformat()} was not found")
            return
        if scheduled and day in A.MISSING_COLUMN_DATES:
            self._fail_run(run, start, "HR export is missing required column(s): manager_id")
            return

        directory_down = scheduled and day in A.DIRECTORY_OUTAGE_DATES
        export = [s for s in self.people.values() if in_hr_export(s.row, start)]
        duplicates = find_duplicates([s.row for s in export])
        clock = start + timedelta(seconds=5)
        successful = failed = 0

        for state in export:
            if not self._needs_sync(state):
                continue
            if directory_down:
                error = ("DEPENDENCY_ERROR", "Directory service unavailable: connection refused")
            else:
                manager = self.people.get(state.row["manager_id"])
                error = sync_record_error(
                    state.row, day, duplicates.get(state.id),
                    manager_has_no_account=manager is not None and manager.account is None,
                    rng=self.rng,
                )

            record_start = clock
            if error is None:
                clock += timedelta(seconds=self.rng.randint(1, 3))
            elif error[0] == "TIMEOUT":
                clock += timedelta(seconds=30)
            else:
                clock += timedelta(seconds=1)

            self._add("sync_record_results", {
                "sync_run_id": run["id"],
                "employee_id": state.id,
                "status": "success" if error is None else "failed",
                "error_type": error[0] if error else None,
                "error_message": error[1] if error else None,
                "started_at": record_start,
                "completed_at": clock,
            })
            if error is None:
                successful += 1
                self._apply_sync(state, clock)
            else:
                failed += 1
                # An outage is not the record's fault, so it does not use up a retry.
                if not directory_down:
                    state.sync_attempts += 1

        run["total_records"] = len(export)
        run["successful_records"] = successful
        run["failed_records"] = failed
        run["skipped_records"] = len(export) - successful - failed
        run["completed_at"] = clock + timedelta(seconds=len(export) // 50)
        if directory_down:
            run["status"] = "failed"
            run["error_message"] = "Directory service unavailable"
            return
        if failed:
            run["status"] = "completed_with_errors"
        initiated_by = "nightly_sync" if scheduled else "manual_sync"
        self._launch_lifecycle_workflows(run["completed_at"] + timedelta(seconds=5), initiated_by)

    def _fail_run(self, run: dict, start: datetime, message: str) -> None:
        run["status"] = "failed"
        run["error_message"] = message
        run["completed_at"] = start + timedelta(seconds=2)

    def _needs_sync(self, state: EmployeeState) -> bool:
        return needs_attribute_sync(
            employment_status=state.row["employment_status"],
            has_account=state.account is not None,
            onboarding_started=state.onboarding_requested,
            changed_since_last_sync=(
                state.account is not None and state.row["updated_at"] > state.account["last_sync_at"]
            ),
            failed_attempts=state.sync_attempts,
        )

    def _apply_sync(self, state: EmployeeState, when: datetime) -> None:
        if state.account is None:
            # New hire: the sync hands the record to the onboarding workflow.
            state.onboarding_requested = True
            self.onboarding_queue.append(state)
            return
        state.account["last_sync_at"] = when
        self._audit(state, "attributes_synced", "Identity attributes updated from HR record", when, "identity_sync")
        self._reconcile_access(state, when)

    def _reconcile_access(self, state: EmployeeState, when: datetime) -> None:
        """Bring birthright access in line with the HR record after a department, site or type change."""
        for kind, name, adding in access_changes(state.identity(), self._desired_access(state)):
            if adding:
                self._assign(state, kind, name, when, audit_source="identity_sync")
            else:
                self._unassign(state, kind, name, when, audit_source="identity_sync")

    # -- lifecycle workflows -------------------------------------------------------------

    def _launch_lifecycle_workflows(self, clock: datetime, initiated_by: str) -> None:
        for state in self.onboarding_queue:
            plan = plan_onboarding(state.identity(), self._desired_access(state))
            clock = self._execute_workflow(state, "onboarding", plan, clock, initiated_by)
        self.onboarding_queue = []

        for state in self.people.values():
            if state.is_duplicate or state.row["created_at"] > clock:
                continue
            due = due_workflows(
                state.row,
                has_account=state.account is not None,
                already_offboarded=state.offboarded,
                has_pending_offboarding=state.offboarding_run is not None,
                leave_applied=state.leave_applied,
                today=clock.date(),
            )
            for work in due:
                clock = self._start_lifecycle_work(state, work, clock, initiated_by)

    def _start_lifecycle_work(self, state: EmployeeState, work: str, clock: datetime, initiated_by: str) -> datetime:
        if work == "offboarding":
            plan = plan_offboarding(state.identity())
            if plan:
                clock = self._execute_workflow(state, "offboarding", plan, clock, initiated_by, run=state.offboarding_run)
            state.offboarded = True
            state.leave_applied = False
        elif work == "queue_offboarding":
            # Future-dated termination: queue offboarding so it shows up as pending work.
            state.offboarding_run = self._add("workflow_runs", {
                "employee_id": state.id,
                "workflow_type": "offboarding",
                "requested_at": clock,
                "started_at": None,
                "completed_at": None,
                "status": "pending",
                "initiated_by": initiated_by,
            })
        elif work == "leave":
            state.leave_applied = True
            plan = plan_leave(state.identity())
            if plan:
                clock = self._execute_workflow(state, "leave", plan, clock, initiated_by)
        elif work == "return_from_leave":
            state.leave_applied = False
            plan = plan_return_from_leave(state.identity())
            if plan:
                clock = self._execute_workflow(state, "return_from_leave", plan, clock, initiated_by)
        return clock

    def _execute_workflow(
        self,
        state: EmployeeState,
        workflow_type: str,
        plan: list[PlannedAction],
        when: datetime,
        initiated_by: str,
        run: dict | None = None,
    ) -> datetime:
        """Run each planned action, record the outcome, and return the time the workflow finished."""
        if run is None:
            run = self._add("workflow_runs", {
                "employee_id": state.id,
                "workflow_type": workflow_type,
                "requested_at": when,
                "started_at": None,
                "completed_at": None,
                "status": "pending",
                "initiated_by": initiated_by,
            })
        run["started_at"] = when
        result = execute_plan(
            plan, SimulatedIdentity(self, state), when, self.rng,
            license_shortage=self._license_shortage(when.date()),
        )
        for outcome in result.outcomes:
            self._add("workflow_actions", {
                "workflow_run_id": run["id"],
                "action_type": outcome.action.action_type,
                "target_name": outcome.action.target,
                "status": outcome.status,
                "started_at": outcome.started_at,
                "completed_at": outcome.completed_at,
                "error_type": outcome.error_type,
                "error_message": outcome.error_message,
            })

        run["completed_at"] = result.finished_at
        run["status"] = result.status
        if result.status == "failed" and initiated_by != "service_desk":
            self._maybe_schedule_rerun(state, workflow_type, result.failed_actions, result.finished_at)
        return result.finished_at + timedelta(seconds=self.rng.randint(2, 10))

    def _license_shortage(self, day: date) -> bool:
        return any(start <= day <= end for start, end in A.LICENSE_SHORTAGE_PERIODS)

    def _apply_action(self, state: EmployeeState, action: PlannedAction, when: datetime) -> None:
        action_type = action.action_type
        source = "workflow_engine"

        if action_type in ASSIGNMENT_ACTIONS:
            kind, adding = ASSIGNMENT_ACTIONS[action_type]
            if adding:
                self._assign(state, kind, action.target, when, audit_source=source)
            else:
                self._unassign(state, kind, action.target, when, audit_source=source)
        elif action_type == "create_account":
            username = username_from_email(state.row["email"], is_taken=self.used_usernames.__contains__)
            self.used_usernames.add(username)
            state.account = self._add("identity_accounts", {
                "employee_id": state.id,
                "username": username,
                "account_status": "active",
                "account_created_at": when,
                "account_disabled_at": None,
                "last_sync_at": when,
            })
            self._audit(state, "account_created", f"Account '{username}' created", when, source)
        elif action_type == "enable_account":
            state.account["account_status"] = "active"
            state.account["account_disabled_at"] = None
            self._audit(state, "account_enabled", "Account enabled", when, source)
        elif action_type == "disable_account":
            state.account["account_status"] = "disabled"
            state.account["account_disabled_at"] = when
            self._audit(state, "account_disabled", "Account disabled", when, source)
        elif action_type == "reset_password":
            # Only the fact of the reset is recorded. No password is generated or stored.
            self._audit(state, "password_reset", "Password reset to a random value", when, source)
        elif action_type == "update_attribute":
            self._audit(state, "attribute_updated", f"Directory attribute '{action.target}' updated", when, source)
        elif action_type == "revoke_session":
            self._audit(state, "sessions_revoked", "All sign-in sessions revoked", when, source)

    def _assign(self, state: EmployeeState, kind: str, name: str, when: datetime, audit_source: str | None) -> None:
        table, name_column, attribute = ASSIGNMENT_KINDS[kind]
        row = self._add(table, {
            "employee_id": state.id,
            name_column: name,
            "assigned_at": when,
            "removed_at": None,
            "status": "active",
        })
        getattr(state, attribute)[name] = row
        if audit_source:
            self._audit(state, f"{kind}_assigned", f"{kind.capitalize()} '{name}' assigned", when, audit_source)

    def _unassign(self, state: EmployeeState, kind: str, name: str, when: datetime, audit_source: str) -> None:
        attribute = ASSIGNMENT_KINDS[kind][2]
        row = getattr(state, attribute).pop(name)
        row["status"] = "removed"
        row["removed_at"] = when
        self._audit(state, f"{kind}_removed", f"{kind.capitalize()} '{name}' removed", when, audit_source)

    def _maybe_schedule_rerun(
        self, state: EmployeeState, workflow_type: str, actions: list[PlannedAction], when: datetime
    ) -> None:
        if self.rng.random() >= A.WORKFLOW_RERUN_PROBABILITY[workflow_type]:
            return
        day = add_business_days(when.date(), self.rng.randint(*A.RERUN_DELAY_BUSINESS_DAYS))
        self._schedule(day, "workflow_rerun", {
            "employee": state.id, "workflow_type": workflow_type, "actions": actions,
        })

    def _on_workflow_rerun(self, when: datetime, payload: dict) -> None:
        """Service desk re-runs the outstanding steps of a failed workflow."""
        state = self.people[payload["employee"]]
        workflow_type = payload["workflow_type"]
        if not can_rerun(workflow_type, state.row["employment_status"], state.row["leave_status"]):
            return
        plan = plan_rerun(workflow_type, payload["actions"], state.identity(), self._desired_access(state))
        if plan:
            self._execute_workflow(state, workflow_type, plan, when, "service_desk")

    # -- data-quality scan ----------------------------------------------------------------

    def _scan_data_quality(self, when: datetime) -> None:
        """Run every rule against every record; open new issues and resolve ones that cleared."""
        existing = [s for s in self.people.values() if s.row["created_at"] <= when]
        access = {
            s.id: AccessSnapshot(
                s.account["account_status"] if s.account else None, len(s.groups), len(s.roles), len(s.licenses)
            )
            for s in existing
        }
        found = find_issues([s.row for s in existing], access, when)
        to_open, to_resolve = issue_changes(list(self.open_issues), found)

        for key in to_open:
            finding = found[key]
            self.open_issues[key] = self._add("data_quality_issues", {
                "employee_id": key[0],
                "issue_type": finding.issue_type,
                "field_name": finding.field_name,
                "severity": finding.severity,
                "description": finding.description,
                "detected_at": when,
                "resolved_at": None,
                "status": "open",
            })

        for key in to_resolve:
            issue = self.open_issues.pop(key)
            issue["resolved_at"] = when
            issue["status"] = "resolved"


def generate(seed: int = A.DEFAULT_SEED) -> dict[str, list[dict]]:
    return Simulation(seed).run()
