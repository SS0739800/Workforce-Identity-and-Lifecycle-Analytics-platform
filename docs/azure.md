# Azure deployment

This is the deployment the project uses. It runs on Azure Container Apps, with PostgreSQL on Neon,
and it is built to cost nothing:

- Container Apps has an always-free monthly grant, and both apps scale to zero when nobody is using them.
- Neon's free Postgres plan has no time limit and needs no card.
- The image lives in GitHub Container Registry, which is currently free for private images.

An AWS version is also in the repository ([aws.md](aws.md)), for anyone who wants to run it on AWS.
It was not used here because AWS has no equivalent that stays free beyond the first 6–12 months.

## What gets deployed

```
  git push ──► GitHub Actions builds the image ──► ghcr.io (private)
                                                        │ pulled with a read-only token
  browser (your IP only) ── HTTPS ──┐                   ▼
  ┌─ Azure resource group: workforce-rg ─────────────────────────────────────┐
  │  Container Apps environment (consumption, scale to zero)                 │
  │    workforce-console  Streamlit, public HTTPS, IP allow-list ─┐          │
  │    workforce-api      FastAPI, internal ingress only ◄────────┘          │
  │  Log Analytics workspace (daily cap 0.1 GB)                              │
  └──────────────────────────────────────────────────────────────┼──────────┘
                                                                 ▼ TLS
                                              Neon PostgreSQL (free plan)
  Subscription budget: email on any spend over $0.01
```

| File | Purpose |
|---|---|
| `.github/workflows/image.yml` | Builds the image on every push and tags it with the commit SHA. |
| `deploy/azure/main.bicep` | Log Analytics, the Container Apps environment, the two apps. |
| `deploy/azure/budget.bicep` | The spending alert (subscription scope). |
| `scripts/azure_deploy.py` | `budget`, `up`, `status`, `down`. |

Design choices:

- **Only the console is public.** It is open to your IP only, over HTTPS (Container Apps provides
  the certificate). The API has internal ingress, so the console can reach it but nothing else can.
- **Secrets are Container Apps secrets.** The Neon URL, the AI keys and the registry token are
  passed as `@secure()` parameters through a temporary file. They are not in the template, the
  deployment outputs or the command line. The console container gets none of them.
- **The image is the one CI built for the exact commit,** referenced by its SHA. `up` refuses to
  deploy a commit whose image doesn't exist yet.
- **Migrations and the data load run from your machine against Neon** (`alembic upgrade head`,
  `load_data.py --if-empty`). A redeploy keeps data changed through the console.

## Cost

| Item | Free allowance | This deployment |
|---|---|---|
| Container Apps (consumption) | 180,000 vCPU-s, 360,000 GiB-s, 2M requests per month | 0.25 vCPU / 0.5 GiB per app, scale to zero, max 1 replica |
| Log Analytics | 5 GB ingestion per month | capped at 0.1 GB per day |
| Neon Postgres | Free plan, no card | 16k rows, well under the storage limit |
| GitHub Container Registry | Storage and bandwidth currently free | one image per commit |
| GitHub Actions | Free minutes on private repos | ~5 minutes per push |
| Budget alert | Free | |

At 0.25 vCPU / 0.5 GiB, the grant covers about **200 hours a month of an active app**. An app is
active while a browser tab has the console open, because Streamlit keeps a live connection. Two
apps are active at the same time. Close the tab when you're done and both apps scale back to zero
within a few minutes. To be certain nothing is left running, use `down`: it deletes the Azure
resources, and `up` brings them back in a few minutes.

The first page load after an idle period takes 10–30 seconds while the apps start (and Neon wakes up).

Prices and allowances change. Check the
[Container Apps pricing page](https://azure.microsoft.com/pricing/details/container-apps/) and
[Neon's plans](https://neon.com/pricing).

## One-time setup

1. **Azure account and CLI.** Create an [Azure free account](https://azure.microsoft.com/free/)
   (it asks for a card to verify your identity). Install the Azure CLI, then sign in:
   ```bash
   winget install --exact --id Microsoft.AzureCLI    # Windows; see Microsoft's docs for macOS/Linux
   az login
   az bicep install
   ```
2. **Neon database.** Sign up at [neon.com](https://neon.com) (free plan, no card). Create a project
   in a US East region, close to the Azure region `eastus`. Copy its connection string into `.env`:
   ```
   NEON_DATABASE_URL=postgresql://...neon.tech/neondb?sslmode=require
   ```
3. **Registry token.** The image is private, so Azure needs a token to pull it. On GitHub, open
   Settings → Developer settings → Personal access tokens → Tokens (classic). Create one with
   **only** the `read:packages` scope and put it in `.env`:
   ```
   GHCR_USERNAME=<your GitHub user name>
   GHCR_READ_TOKEN=<the token>
   ```
4. **First image.** Push to `main` or `sudaiv-work`. The *Build image* workflow (GitHub → Actions)
   publishes `ghcr.io/<user>/workforce-identity:<commit>`.

`.env` is git-ignored. None of these values belong in the repository or in a chat.

## Commands

```bash
python scripts/azure_deploy.py budget --email you@example.com   # once
python scripts/azure_deploy.py up       # deploy the current (pushed) commit
python scripts/azure_deploy.py status
python scripts/azure_deploy.py down     # delete the Azure resources; Neon keeps the data
```

`up` reads your public IP for the allow-list. If your IP changes, run `up` again.

## Troubleshooting

- **No image for commit:** push the commit and wait for the *Build image* workflow to go green.
- **403 when opening the console:** your IP changed; run `up` again.
- **Logs:** `az containerapp logs show -g workforce-rg -n workforce-api --follow`
  (`--type system` shows startup and image-pull events). The same logs are in the Log Analytics
  workspace `workforce-logs`.

## Trade-offs, and what production would use instead

| Here (free) | Production | Why it differs |
|---|---|---|
| Neon free plan, outside Azure | Azure Database for PostgreSQL in a private VNet | The Azure database is free for 12 months only. |
| Container Apps secrets | Key Vault references with a managed identity | Key Vault bills per operation. |
| Image in GHCR, pulled with a personal token | Azure Container Registry with managed-identity pull | ACR has no free tier. |
| Scale to zero (cold starts) | At least one warm replica | Idle replicas use the free grant. |
| IP allow-list, no sign-in | Microsoft Entra ID authentication on the console | Not needed for a single-user demo. |
| Deploy script run by hand | Deploy job in the GitHub workflow (OIDC to Azure) | Fewer moving parts for a demo. |
