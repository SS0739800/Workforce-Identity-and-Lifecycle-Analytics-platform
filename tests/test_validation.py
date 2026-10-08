from datetime import date, datetime, timezone

from app.lifecycle.validation import check_hr_record, check_identity_state, find_duplicates

AS_OF = date(2026, 1, 15)
NOW = datetime(2026, 1, 15, 18, tzinfo=timezone.utc)


def employee(**overrides) -> dict:
    record = {
        "id": 10,
        "employee_id": "EMP00010",
        "first_name": "Alex",
        "last_name": "Smith",
        "email": "alex.smith@northstar-mfg.example",
        "department": "Engineering",
        "job_title": "Process Engineer",
        "manager_id": 3,
        "location": "Dayton Plant",
        "employment_type": "full_time",
        "hire_date": date(2024, 5, 1),
        "termination_date": None,
        "employment_status": "active",
        "leave_status": "none",
        "created_at": datetime(2024, 4, 24, 9, tzinfo=timezone.utc),
        "updated_at": datetime(2024, 4, 24, 9, tzinfo=timezone.utc),
    }
    record.update(overrides)
    return record


def issue_types(findings) -> set[str]:
    return {f.issue_type for f in findings}


def test_valid_record_has_no_findings():
    assert check_hr_record(employee(), AS_OF) == []


def test_missing_required_attributes_block_the_sync():
    findings = check_hr_record(employee(employee_id=None, manager_id=None, job_title=None), AS_OF)
    assert issue_types(findings) == {"missing_employee_id", "missing_manager", "missing_job_title"}
    assert all(f.blocks_sync and f.error_type == "MISSING_ATTRIBUTE" for f in findings)


def test_ceo_is_allowed_to_have_no_manager():
    ceo = employee(job_title="Chief Executive Officer", department="Executive", manager_id=None)
    assert check_hr_record(ceo, AS_OF) == []


def test_badly_formatted_emails_are_rejected():
    for bad in ("alex.smith@northstar-mfg", "alex.smith.northstar-mfg.example", "alex smith@northstar-mfg.example", None):
        findings = check_hr_record(employee(email=bad), AS_OF)
        assert issue_types(findings) == {"invalid_email"}, bad


def test_logistics_becomes_invalid_after_the_merge():
    record = employee(department="Logistics")
    assert check_hr_record(record, date(2026, 3, 31)) == []
    findings = check_hr_record(record, date(2026, 4, 1))
    assert issue_types(findings) == {"invalid_department"}
    assert findings[0].error_type == "INVALID_ATTRIBUTE"


def test_unknown_location_is_reported_but_does_not_block():
    findings = check_hr_record(employee(location="Dayton"), AS_OF)
    assert issue_types(findings) == {"invalid_location"}
    assert not findings[0].blocks_sync


def test_passed_termination_date_with_active_status_is_critical():
    findings = check_hr_record(employee(termination_date=date(2026, 1, 9)), AS_OF)
    assert issue_types(findings) == {"incorrect_employment_status"}
    assert findings[0].severity == "critical"


def test_future_termination_date_is_fine():
    assert check_hr_record(employee(termination_date=date(2026, 2, 1)), AS_OF) == []


def test_terminated_without_date_is_reported():
    findings = check_hr_record(employee(employment_status="terminated"), AS_OF)
    assert issue_types(findings) == {"missing_termination_date"}


def test_terminated_employee_with_leftover_access():
    record = employee(employment_status="terminated", termination_date=date(2026, 1, 2))
    findings = check_identity_state(record, NOW, "active", active_groups=2, active_roles=1, active_licenses=1)
    assert issue_types(findings) == {
        "active_account_for_terminated_employee",
        "stale_group_membership",
        "stale_role_assignment",
        "license_on_inactive_employee",
    }


def test_leftover_access_is_not_flagged_before_overnight_offboarding():
    record = employee(employment_status="terminated", termination_date=AS_OF)
    assert check_identity_state(record, NOW, "active", 2, 1, 1) == []


def test_cleanly_offboarded_employee_has_no_findings():
    record = employee(employment_status="terminated", termination_date=date(2026, 1, 2))
    assert check_identity_state(record, NOW, "disabled", 0, 0, 0) == []


def test_missing_account_respects_grace_period():
    new_hire = employee(created_at=datetime(2026, 1, 14, 9, tzinfo=timezone.utc))
    assert check_identity_state(new_hire, NOW, None, 0, 0, 0) == []
    established = employee()
    assert issue_types(check_identity_state(established, NOW, None, 0, 0, 0)) == {"missing_identity_account"}


def test_duplicates_point_at_the_earlier_record():
    first = employee(id=5)
    second = employee(id=9, employee_id="EMP00099")
    other = employee(id=7, first_name="Jordan")
    assert find_duplicates([second, other, first]) == {9: 5}
