"""Deploy to Azure Container Apps, with the database on Neon (deploy/azure/main.bicep).

    python scripts/azure_deploy.py budget --email you@example.com   once: email me if the subscription spends anything
    python scripts/azure_deploy.py up       migrate and seed Neon, then deploy the image for the current commit
    python scripts/azure_deploy.py status   show the console URL and the running revisions
    python scripts/azure_deploy.py down     delete the Azure resource group (Neon is left as it is)

Uses the Azure CLI's sign-in (`az login`). The image is built by GitHub Actions on push
(.github/workflows/image.yml), so commit and push before `up`. Settings come from .env; see docs/azure.md.
"""

import argparse
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from scripts.deploy_helpers import DeployError, my_public_cidr  # noqa: E402

logger = logging.getLogger("azure_deploy")

TEMPLATE = PROJECT_ROOT / "deploy" / "azure" / "main.bicep"
BUDGET_TEMPLATE = PROJECT_ROOT / "deploy" / "azure" / "budget.bicep"
IMAGE_NAME = "workforce-identity"
PROVIDERS = ["Microsoft.App", "Microsoft.OperationalInsights", "Microsoft.Consumption"]


class DeploySettings(BaseSettings):
    """Deploy-only settings from .env. The app itself never reads these."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    neon_database_url: str | None = None
    ghcr_username: str | None = None
    ghcr_read_token: str | None = None


# --- small helpers (unit-tested in tests/test_deploy_azure.py) ------------------------------------

def sqlalchemy_url(url: str) -> str:
    """Neon's 'postgresql://...?sslmode=require' -> the 'postgresql+psycopg://' form SQLAlchemy uses here."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("postgres", "postgresql", "postgresql+psycopg"):
        raise DeployError("NEON_DATABASE_URL must be a postgresql:// connection string")
    query = dict(urllib.parse.parse_qsl(parts.query))
    query.setdefault("sslmode", "require")  # Neon only accepts TLS connections
    return urllib.parse.urlunsplit(
        ("postgresql+psycopg", parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def image_reference(owner: str, commit: str) -> str:
    return f"ghcr.io/{owner.lower()}/{IMAGE_NAME}:{commit}"


def parameters_file(values: dict, directory: Path) -> Path:
    """Write deployment parameters to a file, so secrets never appear on a command line."""
    path = directory / "parameters.json"
    path.write_text(json.dumps({
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {key: {"value": value} for key, value in values.items()},
    }), encoding="utf-8")
    return path


# --- external commands ---------------------------------------------------------------------------

def az(*args: str) -> dict | list | str | None:
    """Run an Azure CLI command and return its JSON output."""
    executable = shutil.which("az")
    if not executable:
        raise DeployError("Azure CLI not found. Install it (see docs/azure.md), then run `az login`.")
    result = subprocess.run([executable, *args, "--output", "json"], capture_output=True, text=True)
    if result.returncode != 0:
        raise DeployError(f"az {args[0]} {args[1] if len(args) > 1 else ''} failed:\n{result.stderr.strip()}")
    return json.loads(result.stdout) if result.stdout.strip() else None


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def require(settings: DeploySettings, *names: str):
    missing = [name.upper() for name in names if not getattr(settings, name)]
    if missing:
        raise DeployError(f"Set {', '.join(missing)} in .env first (see docs/azure.md)")


def image_exists(owner: str, token: str, commit: str) -> bool:
    """Ask GitHub Container Registry whether the image for this commit has been built."""
    repository = f"{owner.lower()}/{IMAGE_NAME}"
    basic = base64.b64encode(f"{owner}:{token}".encode()).decode()
    request = urllib.request.Request(
        f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repository}:pull",
        headers={"Authorization": f"Basic {basic}"})
    with urllib.request.urlopen(request, timeout=15) as response:
        bearer = json.load(response)["token"]
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{repository}/manifests/{commit}", method="HEAD",
        headers={"Authorization": f"Bearer {bearer}", "Accept": ", ".join([
            "application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
            "application/vnd.docker.distribution.manifest.list.v2+json",
            "application/vnd.docker.distribution.manifest.v2+json"])})
    try:
        with urllib.request.urlopen(request, timeout=15):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def prepare_database(database_url: str):
    """Run the migrations and load the synthetic data into Neon (skipped if it already has data)."""
    environment = {**os.environ, "DATABASE_URL": database_url}
    for step in (["-m", "alembic", "upgrade", "head"], ["scripts/load_data.py", "--if-empty"]):
        logger.info("Neon: %s", " ".join(step))
        result = subprocess.run([sys.executable, *step], cwd=PROJECT_ROOT, env=environment)
        if result.returncode != 0:
            raise DeployError(f"`{' '.join(step)}` failed against Neon")


def wait_for(url: str, minutes: int = 10):
    logger.info("Waiting for %s (the first start pulls the image)", url)
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=20) as response:
                if response.status == 200:
                    logger.info("Console is up")
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(10)
    raise DeployError(f"{url} did not answer within {minutes} minutes. "
                      "Check the logs: az containerapp logs show -g <group> -n <app> --type system")


# --- commands -----------------------------------------------------------------------------------

def cmd_budget(args):
    az("deployment", "sub", "create", "--name", f"{args.project}-budget", "--location", args.location,
       "--template-file", str(BUDGET_TEMPLATE), "--parameters", f"name={args.project}",
       f"alertEmail={args.email}")
    logger.info("Budget alert ready: any spend over $0.01 in a month is emailed to %s", args.email)


def cmd_up(args):
    settings = DeploySettings()
    require(settings, "neon_database_url", "ghcr_username", "ghcr_read_token")
    database_url = sqlalchemy_url(settings.neon_database_url)

    commit = git("rev-parse", "HEAD")
    if git("status", "--porcelain"):
        logger.warning("You have uncommitted changes; only the pushed commit's image is deployed")
    if not image_exists(settings.ghcr_username, settings.ghcr_read_token, commit):
        raise DeployError(f"No image for commit {commit[:7]} yet. Push it and wait for the 'Build image' "
                          "workflow to finish (GitHub → Actions).")
    image = image_reference(settings.ghcr_username, commit)
    logger.info("Image %s", image)

    prepare_database(database_url)

    for namespace in PROVIDERS:  # new subscriptions need these registered once
        az("provider", "register", "--namespace", namespace, "--wait")
    group = f"{args.project}-rg"
    az("group", "create", "--name", group, "--location", args.location)

    cidr = args.allowed_cidr or my_public_cidr()
    logger.info("Console will be reachable from %s only", cidr)
    app_settings = get_settings()
    values = {
        "name": args.project, "image": image, "registryUsername": settings.ghcr_username,
        "registryPassword": settings.ghcr_read_token, "databaseUrl": database_url, "allowedCidr": cidr,
        "groqApiKey": app_settings.groq_api_key or "", "geminiApiKey": app_settings.gemini_api_key or "",
    }
    logger.info("Deploying to resource group %s (a few minutes)", group)
    with tempfile.TemporaryDirectory() as directory:
        result = az("deployment", "group", "create", "--resource-group", group, "--name", args.project,
                    "--template-file", str(TEMPLATE), "--parameters", f"@{parameters_file(values, Path(directory))}")
    outputs = {key: value["value"] for key, value in result["properties"]["outputs"].items()}
    wait_for(outputs["consoleUrl"])
    print(f"\nConsole: {outputs['consoleUrl']}")
    print("Run `python scripts/azure_deploy.py down` when you're done.")


def cmd_status(args):
    group = f"{args.project}-rg"
    if not az("group", "exists", "--name", group):
        print(f"{group}: not deployed")
        return
    for app in (f"{args.project}-console", f"{args.project}-api"):
        info = az("containerapp", "show", "--resource-group", group, "--name", app)
        ingress = info["properties"]["configuration"]["ingress"]
        print(f"{app}: {info['properties']['runningStatus']} · "
              f"{'https://' + ingress['fqdn'] if ingress['external'] else 'internal only'} · "
              f"image {info['properties']['template']['containers'][0]['image'].rsplit(':', 1)[-1][:7]}")


def cmd_down(args):
    group = f"{args.project}-rg"
    if not az("group", "exists", "--name", group):
        logger.info("%s does not exist; nothing to delete", group)
        return
    if not args.yes and input(f"Delete resource group {group} and everything in it? Type its name: ") != group:
        raise DeployError("Not confirmed; nothing deleted")
    logger.info("Deleting %s (a few minutes)", group)
    az("group", "delete", "--name", group, "--yes")
    logger.info("Deleted. The Neon database and the budget alert are kept (both free).")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="workforce", help="resource name prefix")
    parser.add_argument("--location", default="eastus", help="Azure region")
    commands = parser.add_subparsers(dest="command", required=True)
    budget = commands.add_parser("budget", help="create the spending alert (once)")
    budget.add_argument("--email", required=True)
    up = commands.add_parser("up", help="deploy the current commit")
    up.add_argument("--allowed-cidr", help="address allowed in, e.g. 203.0.113.7/32 (default: your public IP)")
    commands.add_parser("status", help="show what is deployed")
    down = commands.add_parser("down", help="delete the Azure resources")
    down.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args()

    configure_logging()
    try:
        account = az("account", "show")
        logger.info("Azure subscription %s (%s)", account["name"], account["id"])
        {"budget": cmd_budget, "up": cmd_up, "status": cmd_status, "down": cmd_down}[args.command](args)
    except DeployError as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
