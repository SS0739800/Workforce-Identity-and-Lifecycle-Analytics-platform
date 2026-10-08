"""Initial schema: all tables for Phase 1.

Revision ID: 5e8cfee4a5ea
Revises: 
Create Date: 2026-10-08 13:55:15.176139

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e8cfee4a5ea'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ai_insight_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('insight_type', sa.String(length=50), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('input_summary', sa.Text(), nullable=True),
    sa.Column('output_summary', sa.Text(), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_insight_runs'))
    )
    op.create_table('employees',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.String(length=20), nullable=True),
    sa.Column('first_name', sa.String(length=100), nullable=False),
    sa.Column('last_name', sa.String(length=100), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=True),
    sa.Column('department', sa.String(length=100), nullable=True),
    sa.Column('job_title', sa.String(length=100), nullable=True),
    sa.Column('manager_id', sa.Integer(), nullable=True),
    sa.Column('location', sa.String(length=100), nullable=True),
    sa.Column('employment_type', sa.String(length=20), nullable=False),
    sa.Column('hire_date', sa.Date(), nullable=False),
    sa.Column('termination_date', sa.Date(), nullable=True),
    sa.Column('employment_status', sa.String(length=20), nullable=False),
    sa.Column('leave_status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("employment_status IN ('active', 'terminated')", name=op.f('ck_employees_employment_status_allowed')),
    sa.CheckConstraint("employment_type IN ('full_time', 'part_time', 'intern', 'contractor')", name=op.f('ck_employees_employment_type_allowed')),
    sa.CheckConstraint("leave_status IN ('none', 'on_leave')", name=op.f('ck_employees_leave_status_allowed')),
    sa.ForeignKeyConstraint(['manager_id'], ['employees.id'], name=op.f('fk_employees_manager_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_employees')),
    sa.UniqueConstraint('employee_id', name=op.f('uq_employees_employee_id'))
    )
    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.String(length=40), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('total_records', sa.Integer(), nullable=False),
    sa.Column('successful_records', sa.Integer(), nullable=False),
    sa.Column('failed_records', sa.Integer(), nullable=False),
    sa.Column('skipped_records', sa.Integer(), nullable=False),
    sa.Column('triggered_by', sa.String(length=50), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('completed', 'completed_with_errors', 'failed')", name=op.f('ck_sync_runs_status_allowed')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_runs')),
    sa.UniqueConstraint('run_id', name=op.f('uq_sync_runs_run_id'))
    )
    op.create_table('attribute_change_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('attribute_name', sa.String(length=50), nullable=False),
    sa.Column('old_value', sa.String(length=255), nullable=True),
    sa.Column('new_value', sa.String(length=255), nullable=True),
    sa.Column('changed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_attribute_change_logs_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attribute_change_logs'))
    )
    op.create_index(op.f('ix_attribute_change_logs_employee_id'), 'attribute_change_logs', ['employee_id'], unique=False)
    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=True),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('event_timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=50), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_audit_events_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events'))
    )
    op.create_index(op.f('ix_audit_events_employee_id'), 'audit_events', ['employee_id'], unique=False)
    op.create_table('data_quality_issues',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('issue_type', sa.String(length=50), nullable=False),
    sa.Column('field_name', sa.String(length=50), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("severity IN ('low', 'medium', 'high', 'critical')", name=op.f('ck_data_quality_issues_severity_allowed')),
    sa.CheckConstraint("status IN ('open', 'resolved')", name=op.f('ck_data_quality_issues_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_data_quality_issues_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_data_quality_issues'))
    )
    op.create_index(op.f('ix_data_quality_issues_employee_id'), 'data_quality_issues', ['employee_id'], unique=False)
    op.create_table('group_memberships',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('group_name', sa.String(length=100), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("status IN ('active', 'removed')", name=op.f('ck_group_memberships_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_group_memberships_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_group_memberships'))
    )
    op.create_index(op.f('ix_group_memberships_employee_id'), 'group_memberships', ['employee_id'], unique=False)
    op.create_table('identity_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('account_status', sa.String(length=20), nullable=False),
    sa.Column('account_created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('account_disabled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_sync_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("account_status IN ('active', 'disabled')", name=op.f('ck_identity_accounts_account_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_identity_accounts_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_identity_accounts')),
    sa.UniqueConstraint('employee_id', name=op.f('uq_identity_accounts_employee_id')),
    sa.UniqueConstraint('username', name=op.f('uq_identity_accounts_username'))
    )
    op.create_table('license_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('license_name', sa.String(length=100), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("status IN ('active', 'removed')", name=op.f('ck_license_assignments_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_license_assignments_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_license_assignments'))
    )
    op.create_index(op.f('ix_license_assignments_employee_id'), 'license_assignments', ['employee_id'], unique=False)
    op.create_table('role_assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('role_name', sa.String(length=100), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('removed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.CheckConstraint("status IN ('active', 'removed')", name=op.f('ck_role_assignments_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_role_assignments_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_role_assignments'))
    )
    op.create_index(op.f('ix_role_assignments_employee_id'), 'role_assignments', ['employee_id'], unique=False)
    op.create_table('sync_record_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sync_run_id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('error_type', sa.String(length=30), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("error_type IN ('MISSING_ATTRIBUTE', 'INVALID_ATTRIBUTE', 'DEPENDENCY_ERROR', 'TIMEOUT', 'PERMISSION_ERROR', 'ALREADY_DISABLED', 'RESOURCE_NOT_FOUND', 'VALIDATION_ERROR')", name=op.f('ck_sync_record_results_error_type_allowed')),
    sa.CheckConstraint("status IN ('success', 'failed')", name=op.f('ck_sync_record_results_status_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_sync_record_results_employee_id_employees')),
    sa.ForeignKeyConstraint(['sync_run_id'], ['sync_runs.id'], name=op.f('fk_sync_record_results_sync_run_id_sync_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sync_record_results'))
    )
    op.create_index(op.f('ix_sync_record_results_employee_id'), 'sync_record_results', ['employee_id'], unique=False)
    op.create_index(op.f('ix_sync_record_results_sync_run_id'), 'sync_record_results', ['sync_run_id'], unique=False)
    op.create_table('workflow_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('workflow_type', sa.String(length=30), nullable=False),
    sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('initiated_by', sa.String(length=50), nullable=False),
    sa.CheckConstraint("status IN ('pending', 'in_progress', 'completed', 'failed')", name=op.f('ck_workflow_runs_status_allowed')),
    sa.CheckConstraint("workflow_type IN ('onboarding', 'offboarding', 'leave', 'return_from_leave')", name=op.f('ck_workflow_runs_workflow_type_allowed')),
    sa.ForeignKeyConstraint(['employee_id'], ['employees.id'], name=op.f('fk_workflow_runs_employee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_runs'))
    )
    op.create_index(op.f('ix_workflow_runs_employee_id'), 'workflow_runs', ['employee_id'], unique=False)
    op.create_table('workflow_actions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('workflow_run_id', sa.Integer(), nullable=False),
    sa.Column('action_type', sa.String(length=40), nullable=False),
    sa.Column('target_name', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('error_type', sa.String(length=30), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.CheckConstraint("action_type IN ('create_account', 'enable_account', 'disable_account', 'reset_password', 'update_attribute', 'add_group_membership', 'remove_group_membership', 'assign_role', 'remove_role', 'assign_license', 'remove_license', 'revoke_session')", name=op.f('ck_workflow_actions_action_type_allowed')),
    sa.CheckConstraint("error_type IN ('MISSING_ATTRIBUTE', 'INVALID_ATTRIBUTE', 'DEPENDENCY_ERROR', 'TIMEOUT', 'PERMISSION_ERROR', 'ALREADY_DISABLED', 'RESOURCE_NOT_FOUND', 'VALIDATION_ERROR')", name=op.f('ck_workflow_actions_error_type_allowed')),
    sa.CheckConstraint("status IN ('success', 'failed', 'skipped')", name=op.f('ck_workflow_actions_status_allowed')),
    sa.ForeignKeyConstraint(['workflow_run_id'], ['workflow_runs.id'], name=op.f('fk_workflow_actions_workflow_run_id_workflow_runs')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_actions'))
    )
    op.create_index(op.f('ix_workflow_actions_workflow_run_id'), 'workflow_actions', ['workflow_run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_workflow_actions_workflow_run_id'), table_name='workflow_actions')
    op.drop_table('workflow_actions')
    op.drop_index(op.f('ix_workflow_runs_employee_id'), table_name='workflow_runs')
    op.drop_table('workflow_runs')
    op.drop_index(op.f('ix_sync_record_results_sync_run_id'), table_name='sync_record_results')
    op.drop_index(op.f('ix_sync_record_results_employee_id'), table_name='sync_record_results')
    op.drop_table('sync_record_results')
    op.drop_index(op.f('ix_role_assignments_employee_id'), table_name='role_assignments')
    op.drop_table('role_assignments')
    op.drop_index(op.f('ix_license_assignments_employee_id'), table_name='license_assignments')
    op.drop_table('license_assignments')
    op.drop_table('identity_accounts')
    op.drop_index(op.f('ix_group_memberships_employee_id'), table_name='group_memberships')
    op.drop_table('group_memberships')
    op.drop_index(op.f('ix_data_quality_issues_employee_id'), table_name='data_quality_issues')
    op.drop_table('data_quality_issues')
    op.drop_index(op.f('ix_audit_events_employee_id'), table_name='audit_events')
    op.drop_table('audit_events')
    op.drop_index(op.f('ix_attribute_change_logs_employee_id'), table_name='attribute_change_logs')
    op.drop_table('attribute_change_logs')
    op.drop_table('sync_runs')
    op.drop_table('employees')
    op.drop_table('ai_insight_runs')
