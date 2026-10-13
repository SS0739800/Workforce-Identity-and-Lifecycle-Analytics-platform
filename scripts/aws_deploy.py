"""Create, update and delete the on-demand AWS environment (deploy/aws/template.yaml).

    python scripts/aws_deploy.py budget --email you@example.com   once: email me if the account spends anything
    python scripts/aws_deploy.py up       create or update the stack, upload the release and data, start the app
    python scripts/aws_deploy.py push     upload the latest commit and data again and restart the app
    python scripts/aws_deploy.py status   show the stack state and URLs
    python scripts/aws_deploy.py down     delete everything the stack created

Uses the AWS CLI's credentials and default region. Deploys the last commit (`git archive HEAD`),
never uncommitted files or .env. See docs/aws.md.
"""

import argparse
import logging
import secrets
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, WaiterError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import PROJECT_ROOT, get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from scripts.deploy_helpers import DeployError, my_public_cidr  # noqa: E402

logger = logging.getLogger("aws_deploy")

TEMPLATE = PROJECT_ROOT / "deploy" / "aws" / "template.yaml"
BUDGET_TEMPLATE = PROJECT_ROOT / "deploy" / "aws" / "budget.yaml"
RELEASE_KEY = "release/app.tar.gz"
# SSM parameter names under /<project>/. SecureString parameters (standard tier) are free.
OPTIONAL_KEYS = {"groq-api-key": "groq_api_key", "gemini-api-key": "gemini_api_key"}


# --- small helpers (unit-tested in tests/test_deploy_aws.py) --------------------------------------

def new_password(length: int = 32) -> str:
    """Letters and digits only, so it can go into a database URL without escaping."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def outputs(stack: dict) -> dict[str, str]:
    return {item["OutputKey"]: item["OutputValue"] for item in stack.get("Outputs", [])}


# --- AWS steps -----------------------------------------------------------------------------------

def describe_stack(cfn, name: str) -> dict | None:
    try:
        return cfn.describe_stacks(StackName=name)["Stacks"][0]
    except ClientError as error:
        if "does not exist" in str(error):
            return None
        raise


def log_failure_events(cfn, name: str):
    for event in cfn.describe_stack_events(StackName=name)["StackEvents"]:
        if event["ResourceStatus"].endswith("_FAILED"):
            logger.error("%s %s: %s", event["LogicalResourceId"], event["ResourceStatus"],
                         event.get("ResourceStatusReason", ""))


def deploy_stack(cfn, name: str, template: Path, parameters: dict[str, str]) -> tuple[dict, bool]:
    """Create the stack, or update it if it exists. Returns (stack, created)."""
    existing = describe_stack(cfn, name)
    if existing and existing["StackStatus"] == "ROLLBACK_COMPLETE":
        # A failed first create leaves an empty stack that can only be deleted.
        logger.info("Removing the failed previous attempt")
        cfn.delete_stack(StackName=name)
        cfn.get_waiter("stack_delete_complete").wait(StackName=name)
        existing = None

    arguments = {
        "StackName": name,
        "TemplateBody": template.read_text(encoding="utf-8"),
        "Parameters": [{"ParameterKey": key, "ParameterValue": value} for key, value in parameters.items()],
        "Capabilities": ["CAPABILITY_IAM"],
    }
    try:
        if existing:
            logger.info("Updating stack %s", name)
            cfn.update_stack(**arguments)
            waiter = "stack_update_complete"
        else:
            logger.info("Creating stack %s (RDS takes about 10 minutes)", name)
            cfn.create_stack(**arguments, Tags=[{"Key": "project", "Value": name}])
            waiter = "stack_create_complete"
    except ClientError as error:
        if "No updates are to be performed" not in str(error):
            raise
        logger.info("Stack %s is already up to date", name)
        return describe_stack(cfn, name), False

    try:
        cfn.get_waiter(waiter).wait(StackName=name, WaiterConfig={"Delay": 20, "MaxAttempts": 180})
    except WaiterError as error:
        log_failure_events(cfn, name)
        raise DeployError(f"Stack {name} did not deploy; the failed resources are listed above") from error
    return describe_stack(cfn, name), not existing


def postgres_version(rds) -> str:
    """RDS's current default PostgreSQL 16 minor version (old minors are retired over time)."""
    versions = rds.describe_db_engine_versions(Engine="postgres", EngineVersion="16", DefaultOnly=True)
    return versions["DBEngineVersions"][0]["EngineVersion"]


def ensure_parameters(ssm, prefix: str):
    """Create the database password once, and copy the optional AI keys from .env. Values are never logged."""
    name = f"{prefix}/db-password"
    try:
        ssm.put_parameter(Name=name, Value=new_password(), Type="SecureString", Overwrite=False,
                          Description="Master password for the workforce RDS database")
        logger.info("Created %s", name)
    except ClientError as error:
        if error.response["Error"]["Code"] != "ParameterAlreadyExists":
            raise

    settings = get_settings()
    for parameter, setting in OPTIONAL_KEYS.items():
        value = getattr(settings, setting)
        if value:
            ssm.put_parameter(Name=f"{prefix}/{parameter}", Value=value, Type="SecureString", Overwrite=True)
            logger.info("Stored %s/%s from .env", prefix, parameter)
        else:
            logger.info("No %s in .env; the AI endpoints will return computed data only", setting.upper())


def upload_release(s3, bucket: str):
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=PROJECT_ROOT, capture_output=True, text=True,
                           check=True).stdout.strip()
    if dirty:
        logger.warning("You have uncommitted changes; only the last commit is deployed")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=PROJECT_ROOT, capture_output=True,
                            text=True, check=True).stdout.strip()
    archive = subprocess.run(["git", "archive", "--format=tar.gz", "HEAD"], cwd=PROJECT_ROOT,
                             capture_output=True, check=True).stdout
    s3.put_object(Bucket=bucket, Key=RELEASE_KEY, Body=archive, Metadata={"commit": commit})
    logger.info("Uploaded commit %s (%.1f MB)", commit, len(archive) / 1e6)


def upload_data(s3, bucket: str):
    files = sorted(get_settings().raw_data_dir.glob("*.csv"))
    if not files:
        raise DeployError("No CSV files in data/raw. Run `python scripts/generate_data.py` first.")
    for path in files:
        s3.upload_file(str(path), bucket, f"raw/{path.name}")
    logger.info("Uploaded %d CSV files to s3://%s/raw/", len(files), bucket)


def restart_app(ssm, instance_id: str):
    """Run the release script on the instance through SSM Run Command (no SSH, no open port)."""
    logger.info("Restarting the app on %s (rebuilds the image, a few minutes)", instance_id)
    command = ssm.send_command(
        InstanceIds=[instance_id], DocumentName="AWS-RunShellScript",
        Parameters={"commands": ["/usr/local/bin/workforce-release"], "executionTimeout": ["1800"]},
        Comment="workforce: deploy the latest release",
    )["Command"]["CommandId"]
    while True:
        time.sleep(10)
        try:
            result = ssm.get_command_invocation(CommandId=command, InstanceId=instance_id)
        except ClientError as error:
            if "InvocationDoesNotExist" in str(error):
                continue
            raise
        if result["Status"] not in ("Pending", "InProgress", "Delayed"):
            break
    tail = "\n".join(result["StandardOutputContent"].splitlines()[-5:])
    if result["Status"] != "Success":
        raise DeployError(f"Restart {result['Status']}:\n{tail}\n{result['StandardErrorContent'][-2000:]}")
    logger.info("Restart finished:\n%s", tail)


def wait_until_healthy(url: str, minutes: int = 30):
    logger.info("Waiting for %s (first boot installs Docker and builds the image)", url)
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200:
                    logger.info("API is healthy")
                    return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(15)
    raise DeployError(f"{url} was not healthy after {minutes} minutes. Check the /<project> log group "
                      "and /var/log/cloud-init-output.log on the instance (via Session Manager).")


def show_urls(stack: dict):
    values = outputs(stack)
    print(f"\nConsole:  {values['ConsoleUrl']}\nAPI docs: {values['ApiDocsUrl']}")
    print(f"Logs:     CloudWatch log group {values['LogGroupName']}")
    print("Run `python scripts/aws_deploy.py down` when you're done, so nothing keeps running.")


# --- commands -----------------------------------------------------------------------------------

def cmd_budget(session, args):
    stack, _ = deploy_stack(session.client("cloudformation"), f"{args.project}-budget", BUDGET_TEMPLATE,
                            {"ProjectName": args.project, "AlertEmail": args.email})
    logger.info("Budget alert %s: any spend over $0.01 in a month is emailed to %s",
                stack["StackStatus"], args.email)


def cmd_up(session, args):
    cfn, s3, ssm = session.client("cloudformation"), session.client("s3"), session.client("ssm")
    ensure_parameters(ssm, f"/{args.project}")
    cidr = args.allowed_cidr or my_public_cidr()
    logger.info("Console and API will be reachable from %s only", cidr)

    before = describe_stack(cfn, args.project)
    old_instance = outputs(before).get("InstanceId") if before else None
    parameters = {
        "ProjectName": args.project, "AllowedCidr": cidr,
        "InstanceType": args.instance_type, "DBInstanceClass": args.db_instance_class,
    }
    if before:
        # Keep the running database's version; RDS upgrades minor versions itself.
        parameters["DBEngineVersion"] = next(p["ParameterValue"] for p in before["Parameters"]
                                             if p["ParameterKey"] == "DBEngineVersion")
    else:
        parameters["DBEngineVersion"] = postgres_version(session.client("rds"))
        logger.info("PostgreSQL %s", parameters["DBEngineVersion"])
    stack, _ = deploy_stack(cfn, args.project, TEMPLATE, parameters)
    values = outputs(stack)
    upload_data(s3, values["BucketName"])
    upload_release(s3, values["BucketName"])
    # A new instance picks the release up by itself on first boot; an existing one is told to restart.
    if values["InstanceId"] == old_instance:
        restart_app(ssm, values["InstanceId"])
    wait_until_healthy(values["HealthUrl"])
    show_urls(stack)


def cmd_push(session, args):
    stack = describe_stack(session.client("cloudformation"), args.project)
    if not stack:
        raise DeployError(f"No stack named {args.project}. Run `up` first.")
    values = outputs(stack)
    s3 = session.client("s3")
    upload_data(s3, values["BucketName"])
    upload_release(s3, values["BucketName"])
    restart_app(session.client("ssm"), values["InstanceId"])
    wait_until_healthy(values["HealthUrl"])
    show_urls(stack)


def cmd_status(session, args):
    cfn = session.client("cloudformation")
    for name in (args.project, f"{args.project}-budget"):
        stack = describe_stack(cfn, name)
        print(f"{name}: {stack['StackStatus'] if stack else 'not deployed'}")
        for key, value in (outputs(stack) if stack else {}).items():
            print(f"  {key}: {value}")


def cmd_down(session, args):
    cfn = session.client("cloudformation")
    stack = describe_stack(cfn, args.project)
    if not stack:
        logger.info("No stack named %s; nothing to delete", args.project)
        return
    if not args.yes and input(f"Delete stack {args.project}, its database and its bucket? Type the stack name: ") \
            != args.project:
        raise DeployError("Not confirmed; nothing deleted")

    bucket = outputs(stack).get("BucketName")
    if bucket:
        # CloudFormation can't delete a bucket that still has objects in it.
        session.resource("s3").Bucket(bucket).objects.all().delete()
        logger.info("Emptied s3://%s", bucket)
    logger.info("Deleting stack %s (RDS takes a few minutes)", args.project)
    cfn.delete_stack(StackName=args.project)
    try:
        cfn.get_waiter("stack_delete_complete").wait(StackName=args.project,
                                                     WaiterConfig={"Delay": 20, "MaxAttempts": 180})
    except WaiterError as error:
        log_failure_events(cfn, args.project)
        raise DeployError("Delete did not finish; check the CloudFormation console") from error
    logger.info("Deleted. The SSM parameters under /%s are kept (they are free); the budget alert stays too.",
                args.project)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--project", default="workforce", help="stack name and resource prefix")
    parser.add_argument("--profile", help="AWS CLI profile (default: the CLI's default)")
    parser.add_argument("--region", help="AWS region (default: the CLI's default)")
    commands = parser.add_subparsers(dest="command", required=True)

    budget = commands.add_parser("budget", help="create the spending alert (once)")
    budget.add_argument("--email", required=True)
    up = commands.add_parser("up", help="create or update the environment and start the app")
    up.add_argument("--allowed-cidr", help="address allowed in, e.g. 203.0.113.7/32 (default: your public IP)")
    up.add_argument("--instance-type", default="t3.micro", choices=["t3.micro", "t3.small"])
    up.add_argument("--db-instance-class", default="db.t4g.micro", choices=["db.t4g.micro", "db.t3.micro"])
    commands.add_parser("push", help="deploy the latest commit to the running environment")
    commands.add_parser("status", help="show the stacks and their outputs")
    down = commands.add_parser("down", help="delete the environment")
    down.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    args = parser.parse_args()

    configure_logging()
    logging.getLogger("botocore").setLevel(logging.WARNING)
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    try:
        identity = session.client("sts").get_caller_identity()
        logger.info("AWS account %s, region %s", identity["Account"], session.region_name)
        {"budget": cmd_budget, "up": cmd_up, "push": cmd_push, "status": cmd_status, "down": cmd_down}[
            args.command](session, args)
    except NoCredentialsError:
        logger.error("No AWS credentials. Run `aws login` or `aws configure` first (see docs/aws.md).")
        return 1
    except (DeployError, ClientError) as error:
        logger.error("%s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
