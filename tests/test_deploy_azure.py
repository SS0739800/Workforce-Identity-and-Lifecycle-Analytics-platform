"""Checks on the Azure deployment (deploy/azure, scripts/azure_deploy.py) that don't need an Azure account.

The Bicep templates are compiled to ARM JSON and the properties that keep the deployment free and
private are asserted on the result. The compile step needs the Bicep CLI: on PATH, installed by
`az bicep install`, or named by the BICEP environment variable. Without it those tests are skipped.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT
from scripts.azure_deploy import image_reference, parameters_file, sqlalchemy_url
from scripts.deploy_helpers import DeployError

DEPLOY = PROJECT_ROOT / "deploy" / "azure"


def bicep_cli() -> str | None:
    candidates = [os.environ.get("BICEP"), shutil.which("bicep"),
                  str(Path.home() / ".azure" / "bin" / ("bicep.exe" if os.name == "nt" else "bicep"))]
    return next((c for c in candidates if c and Path(c).exists()), None)


@pytest.fixture(scope="module")
def compiled():
    cli = bicep_cli()
    if not cli:
        pytest.skip("Bicep CLI not installed")

    def build(name: str) -> dict:
        result = subprocess.run([cli, "build", str(DEPLOY / f"{name}.bicep"), "--stdout"],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "Warning" not in result.stderr, result.stderr  # linter findings are printed as warnings
        return json.loads(result.stdout)

    return {"main": build("main"), "budget": build("budget")}


def resources(template: dict, kind: str) -> list[dict]:
    return [r for r in template["resources"] if r["type"] == kind]


def app(template: dict, suffix: str) -> dict:
    [found] = [r for r in resources(template, "Microsoft.App/containerApps") if suffix in r["name"]]
    return found["properties"]


def test_only_free_resource_types(compiled):
    """No container registry, Key Vault, load balancer or database: those are billed."""
    assert {r["type"] for r in compiled["main"]["resources"]} == {
        "Microsoft.OperationalInsights/workspaces", "Microsoft.App/managedEnvironments",
        "Microsoft.App/containerApps"}
    [environment] = resources(compiled["main"], "Microsoft.App/managedEnvironments")
    assert "workloadProfiles" not in environment["properties"]  # consumption only: covered by the free grant


def test_apps_scale_to_zero_at_the_smallest_size(compiled):
    variables = compiled["main"]["variables"]
    assert variables["scaleToZero"] == {"minReplicas": 0, "maxReplicas": 1}
    assert variables["smallest"]["memory"] == "0.5Gi"
    for suffix in ("api", "console"):
        template = app(compiled["main"], suffix)["template"]
        assert template["scale"] == "[variables('scaleToZero')]"
        assert template["containers"][0]["resources"] == "[variables('smallest')]"


def test_api_is_internal_and_console_is_limited_to_one_address(compiled):
    assert app(compiled["main"], "api")["configuration"]["ingress"]["external"] is False
    ingress = app(compiled["main"], "console")["configuration"]["ingress"]
    assert ingress["external"] is True
    assert ingress["ipSecurityRestrictions"] == [
        {"name": "owner", "action": "Allow", "ipAddressRange": "[parameters('allowedCidr')]"}]


def test_secrets_are_secure_parameters_and_never_reach_the_console(compiled):
    parameters = compiled["main"]["parameters"]
    secrets = ("registryPassword", "databaseUrl", "groqApiKey", "geminiApiKey")
    for name in secrets:
        assert parameters[name]["type"] == "securestring"
    console = json.dumps(app(compiled["main"], "console"))
    assert "databaseUrl" not in console and "ApiKey" not in console
    outputs = json.dumps(compiled["main"]["outputs"])
    assert not any(name in outputs for name in secrets)


def test_log_ingestion_is_capped_below_the_free_allowance(compiled):
    [workspace] = resources(compiled["main"], "Microsoft.OperationalInsights/workspaces")
    assert workspace["properties"]["workspaceCapping"]["dailyQuotaGb"] == "[json('0.1')]"


def test_budget_alerts_on_any_actual_spend(compiled):
    [budget] = resources(compiled["budget"], "Microsoft.Consumption/budgets")
    actual = [n for n in budget["properties"]["notifications"].values() if n["thresholdType"] == "Actual"]
    assert budget["properties"]["amount"] == 1 and actual[0]["threshold"] == 1


@pytest.mark.parametrize("url", [
    "postgresql://user:secret@ep-quiet-1.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require",
    "postgres://user:secret@ep-quiet-1.us-east-1.aws.neon.tech/neondb",
])
def test_neon_url_becomes_a_tls_psycopg_url(url):
    converted = sqlalchemy_url(url)
    assert converted.startswith("postgresql+psycopg://user:secret@ep-quiet-1.us-east-1.aws.neon.tech/neondb?")
    assert "sslmode=require" in converted


def test_non_postgres_url_is_rejected():
    with pytest.raises(DeployError):
        sqlalchemy_url("mysql://user:secret@host/db")


def test_image_reference_is_lowercase():
    assert image_reference("SS0739800", "abc123") == "ghcr.io/ss0739800/workforce-identity:abc123"


def test_parameters_file_wraps_values(tmp_path):
    path = parameters_file({"image": "x", "databaseUrl": "secret"}, tmp_path)
    assert json.loads(path.read_text())["parameters"] == {"image": {"value": "x"}, "databaseUrl": {"value": "secret"}}
