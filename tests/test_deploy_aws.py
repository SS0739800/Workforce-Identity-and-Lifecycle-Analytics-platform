"""Checks on the AWS deployment files (deploy/aws) that don't need an AWS account.

The templates are linted with cfn-lint, and the properties that keep the environment free and
private are asserted directly, so a later edit can't quietly open the database or add a paid service.
"""

import re

import pytest
from cfnlint.api import ManualArgs, lint_file
from cfnlint.decode.cfn_yaml import loads

from app.core.config import PROJECT_ROOT
from scripts.aws_deploy import new_password
from scripts.deploy_helpers import DeployError, as_cidr

DEPLOY = PROJECT_ROOT / "deploy" / "aws"


def read_template(name: str) -> dict:
    return loads((DEPLOY / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def resources() -> dict:
    return read_template("template.yaml")["Resources"]


def of_type(resources: dict, kind: str) -> list[dict]:
    return [r["Properties"] for r in resources.values() if r["Type"] == kind]


@pytest.mark.parametrize("name", ["template.yaml", "budget.yaml"])
def test_templates_pass_cfn_lint(name):
    matches = lint_file(DEPLOY / name, ManualArgs(regions=["us-east-2"]))
    assert not matches, "\n".join(str(m) for m in matches)


def test_only_free_tier_services(resources):
    paid = {"AWS::ElasticLoadBalancingV2::LoadBalancer", "AWS::EC2::NatGateway", "AWS::EC2::EIP",
            "AWS::SecretsManager::Secret", "AWS::ECS::Service", "AWS::ECS::Cluster"}
    assert not paid & {r["Type"] for r in resources.values()}


def test_database_is_private_and_password_comes_from_ssm(resources):
    [database] = of_type(resources, "AWS::RDS::DBInstance")
    assert database["PubliclyAccessible"] is False
    assert database["MultiAZ"] is False
    assert "{{resolve:ssm-secure:" in str(database["MasterUserPassword"])

    [db_group] = [p for p in of_type(resources, "AWS::EC2::SecurityGroup") if "PostgreSQL" in p["GroupDescription"]]
    [rule] = db_group["SecurityGroupIngress"]
    assert "SourceSecurityGroupId" in rule and "CidrIp" not in rule


def test_app_ports_are_open_to_one_address_only(resources):
    rules = [rule for group in of_type(resources, "AWS::EC2::SecurityGroup")
             for rule in group["SecurityGroupIngress"]]
    assert not any(str(rule.get("CidrIp")) == "0.0.0.0/0" for rule in rules)
    assert sorted(rule["FromPort"] for rule in rules if "CidrIp" in rule) == [8000, 8501]  # no SSH


def test_instance_permissions_are_scoped(resources):
    [role] = of_type(resources, "AWS::IAM::Role")
    statements = [s for policy in role["Policies"] for s in policy["PolicyDocument"]["Statement"]]
    for statement in statements:
        assert "*" not in str(statement["Action"])
        assert statement["Resource"] != "*"
    [instance] = of_type(resources, "AWS::EC2::Instance")
    assert instance["MetadataOptions"]["HttpTokens"] == "required"


def test_bucket_blocks_public_access(resources):
    [bucket] = of_type(resources, "AWS::S3::Bucket")
    assert all(bucket["PublicAccessBlockConfiguration"].values())


def test_deploy_script_passes_only_known_parameters():
    """A misspelt parameter name would only fail at deploy time, so check it here."""
    declared = set(read_template("template.yaml")["Parameters"]) | set(read_template("budget.yaml")["Parameters"])
    source = (PROJECT_ROOT / "scripts" / "aws_deploy.py").read_text(encoding="utf-8")
    passed = set(re.findall(r'"(\w+)": args\.', source)) | {"DBEngineVersion"}
    assert passed <= declared


def test_start_script_never_traces_commands():
    """`set -x` would print the database password and API keys into the logs."""
    script = (DEPLOY / "start.sh").read_text(encoding="utf-8")
    assert not re.search(r"^\s*set\s+-\w*x", script, re.MULTILINE)
    assert "\r" not in script


def test_image_excludes_secrets_and_runs_unprivileged():
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert re.search(r"^USER \w+", (PROJECT_ROOT / "Dockerfile").read_text(encoding="utf-8"), re.MULTILINE)


def test_password_is_url_safe():
    password = new_password()
    assert len(password) == 32 and password.isalnum()
    assert new_password() != password


def test_as_cidr_turns_a_public_address_into_a_single_host_range():
    assert as_cidr("8.8.8.8\n") == "8.8.8.8/32"


# Private ranges, a documentation range (not routable) and IPv6 are all rejected.
@pytest.mark.parametrize("text", ["10.0.0.5", "192.168.1.20", "203.0.113.7", "2001:4860:4860::8888"])
def test_as_cidr_rejects_other_addresses(text):
    with pytest.raises(DeployError):
        as_cidr(text)
