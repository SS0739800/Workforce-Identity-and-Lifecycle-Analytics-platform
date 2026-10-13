# AWS deployment

> The project's own deployment is on Azure ([azure.md](azure.md)), because that can stay free with
> no time limit. This AWS version is complete and kept for anyone who prefers AWS. On AWS it is free
> only within the free tier or new-account credits.

An on-demand demo environment: one command creates it, one deletes it. It is built to stay inside
the AWS free tier, so some choices differ from what a production team would pick. Those trade-offs
are listed below.

## What gets deployed

```
                 your IP only (security group)
  browser ──────────────────────────────────────┐
                                                │ :8501 console, :8000 API
  ┌─ VPC 10.20.0.0/16 ──────────────────────────┼───────────────────────┐
  │  public subnet                              ▼                       │
  │   EC2 t3.micro (Amazon Linux 2023, Docker)                          │
  │     ├─ workforce-streamlit ──HTTP──► workforce-api                  │
  │     └─ one-off jobs: alembic upgrade, load_data --if-empty          │
  │              │ 5432 (from the app security group only)              │
  │  private subnets (no internet route)                                │
  │   RDS PostgreSQL 16, db.t4g.micro, 20 GB, encrypted, not public     │
  └─────────────────────────────────────────────────────────────────────┘
  S3 bucket          release (git archive of the last commit) + generated CSVs
  SSM Parameter Store  /workforce/db-password, groq-api-key, gemini-api-key (SecureString)
  CloudWatch Logs    /workforce: streams api, streamlit, jobs (kept 7 days)
  IAM role           read this bucket, read /workforce/* parameters, write this log group, SSM agent
  AWS Budgets        email on any spend over $0.01 (separate stack, stays after `down`)
```

Files:

| File | Purpose |
|---|---|
| `Dockerfile` | One image for the API, the console and the jobs. |
| `deploy/aws/template.yaml` | CloudFormation: network, RDS, S3, logs, IAM, EC2. |
| `deploy/aws/budget.yaml` | CloudFormation: the spending alert. |
| `deploy/aws/start.sh` | Runs on the instance: build, migrate, load if empty, start containers. |
| `scripts/aws_deploy.py` | `budget`, `up`, `push`, `status`, `down`. |

## How a deploy works

1. `aws_deploy.py up` generates a random database password and stores it as an SSM SecureString.
   It also copies `GROQ_API_KEY` and `GEMINI_API_KEY` from your `.env`, if they are set. No secret is
   printed, put in the template, or passed as a stack parameter.
2. CloudFormation creates the stack. RDS reads its password from SSM through a dynamic reference.
3. The script uploads `data/raw/*.csv` and a `git archive` of the last commit to the bucket. Only
   committed files are deployed; `.env` and `data/` are never in the archive.
4. On first boot the instance installs Docker, adds 1 GB of swap, waits for the release in S3 and
   runs `start.sh`. That script builds the image, runs `alembic upgrade head`, and loads the CSVs
   only if the database is empty. It then starts the two containers.
5. The script polls `/health` until the API answers and prints the URLs.

`push` repeats steps 3–5 on the running instance through SSM Run Command, with no SSH involved. Data
changed through the console (syncs, re-runs, scans) survives a push, because the load is skipped
when the database already has data.

## Cost

AWS changed its free tier on 15 July 2025.

- **Accounts created on or after 15 July 2025** choose a Free plan or a Paid plan and get $100–$200
  in credits for six months. EC2, RDS and the public IPv4 address are paid from the credits. A
  Free-plan account can't be charged: when the credits or the six months run out, AWS closes the
  account unless you upgrade it.
- **Older accounts** get 750 hours a month of a t2/t3.micro instance and of a single-AZ micro RDS
  instance for the first 12 months. Anything outside that is billed.

While the stack is running it uses a t3.micro, a db.t4g.micro, 16 GB of EBS, 20 GB of RDS storage
and one public IPv4 address. All of these are covered by the free tier or by credits. S3, CloudWatch
Logs (under 5 GB), SSM standard parameters, IAM, CloudFormation and the budget alert are free.
Nothing is created that bills by the hour regardless: no load balancer, NAT gateway, Elastic IP or
Secrets Manager.

The habit that keeps it free on any account: **`up` for a demo, `down` afterwards.** The budget
alert emails you if real money is ever owed. It counts credits, so usage paid for by credits does
not trigger it.

Prices and free-tier rules change; check the
[AWS Free Tier page](https://aws.amazon.com/free/) before relying on the above.

## Before the first deploy

1. **Check the account plan.** In the AWS console, open Billing and Cost Management. The home page
   shows whether the account is on the Free or Paid plan, and how much credit is left. If you
   want a guarantee of no charges, use a Free-plan account.
2. **Sign the CLI in.** AWS CLI 2.32 or later can use your console sign-in instead of long-lived
   access keys:
   ```bash
   aws login --profile workforce                        # opens the browser to sign in
   aws configure set region us-east-2 --profile workforce
   aws sts get-caller-identity --profile workforce      # should print your account and user
   ```
   Use an IAM user or IAM Identity Center user with admin rights, not the root user. If you already
   have stale access keys in `~/.aws/credentials`, a separate profile keeps them out of the way.
   Pass `--profile workforce` to every `aws_deploy.py` command below.
3. **Install the deploy tools** (already in `requirements-dev.txt`): `pip install -r requirements-dev.txt`.
4. **Generate the data** if `data/raw/` is empty: `python scripts/generate_data.py`.

## Commands

```bash
python scripts/aws_deploy.py --profile workforce budget --email you@example.com   # once
python scripts/aws_deploy.py --profile workforce up       # ~15-20 min the first time (RDS + image build)
python scripts/aws_deploy.py --profile workforce status
python scripts/aws_deploy.py --profile workforce push     # after committing code changes
python scripts/aws_deploy.py --profile workforce down     # deletes the stack, database and bucket
```

`up` opens the console and API to your current public IP only (`/32`). If your IP changes, run `up`
again to update the rule. `down` keeps the SSM parameters, which are free. To remove those as well:
`aws ssm delete-parameters --names /workforce/db-password /workforce/groq-api-key /workforce/gemini-api-key`.

## Troubleshooting

- **Logs:** `aws logs tail /workforce --follow --profile workforce`, or CloudWatch → Log groups →
  `/workforce`.
- **Shell on the instance:** EC2 console → the instance → Connect → Session Manager. There is no SSH
  port and no key pair. The first-boot log is `/var/log/cloud-init-output.log`.
- **Stack failed:** `up` prints the failed resources. A failed first create is cleaned up
  automatically on the next `up`.

## Trade-offs, and what production would use instead

| Here (free) | Production | Why it differs |
|---|---|---|
| One EC2 instance running both containers | ECS Fargate services behind an Application Load Balancer | Fargate and ALBs have no free tier. |
| HTTP on ports 8000/8501, restricted to one IP | HTTPS via ACM certificate on the ALB, private app subnets | ACM certificates attach to a load balancer or CloudFront. |
| Secrets in SSM Parameter Store SecureString, written to a root-only env file on the instance | Secrets Manager with rotation, injected by ECS | Secrets Manager costs per secret per month. |
| Image built on the instance from the release | Built in CI, pushed to ECR, deployed by tag | Avoids ECR storage and a CI pipeline for a demo. |
| RDS single-AZ, no backups, deleted with the stack | Multi-AZ, automated backups, deletion protection | The data is synthetic and reloadable. |
| Public subnet for the instance | Private subnets with NAT or VPC endpoints | NAT gateways and interface endpoints bill hourly. |

Every item in the right-hand column is a template change, not an application change: the app
already reads its configuration from environment variables and logs to stdout.
