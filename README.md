# SmokeMonitor POC

This repository is the reproducible proof of concept for the workflow in
[FlowChart.drawio](./FlowChart.drawio). It contains the first vertical slice:

- a deliberately fault-injectable FastAPI commerce application;
- ten Playwright smoke tests covering health, catalog, product details,
  checkout, orders, admin access, and failure handling;
- a Jenkins pipeline with two retries;
- Terraform for a minimal Azure Container Apps environment and Log Analytics;
- a GitHub Actions validation pipeline.

The Jenkins plugin, triage service, and notifications are the next milestones.
They should consume the test artifacts produced here rather than hiding the
evidence inside a custom UI.

## Run locally

Requirements: Docker Desktop (or Docker Engine with Compose).

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8000/health
```

The application is at <http://localhost:8000>; the admin page is at
<http://localhost:8000/admin>. The admin page is a visual operations console.
Enter the value of `ADMIN_TOKEN` from `.env` into the token field. For API
examples, the default local token is `local-admin-token`:

```bash
curl -X POST http://localhost:8000/admin/faults/http_500 \
  -H 'X-Admin-Token: local-admin-token'
curl -H 'X-Admin-Token: local-admin-token' \
  -X DELETE http://localhost:8000/admin/faults
```

To run browser tests locally:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r app/requirements.txt -r smoke-tests/requirements.txt
python -m playwright install --with-deps chromium
BASE_URL=http://localhost:8000 pytest smoke-tests
```

## Azure deployment learning path

Terraform creates the Azure runtime; it does not authenticate to your
subscription automatically and it does not contain your secrets.

1. Install Azure CLI, Terraform, Docker, and Git.
2. Log in with `az login`.
3. Find your subscription with `az account list --output table`.
4. Create a local variables file:

   ```bash
   cd infra/terraform
   cp terraform.tfvars.example terraform.tfvars
   ```

5. Edit `terraform.tfvars` with your subscription ID and a long random admin
   token. Set `location` to the Azure region closest to your users, and set
   `cost_alert_email` to receive budget warnings. This file is ignored by Git
   because it contains secrets.
6. Initialize and review:

   ```bash
   az provider register --namespace Microsoft.Resources
   az provider register --namespace Microsoft.App
   az provider register --namespace Microsoft.OperationalInsights
   az provider register --namespace Microsoft.Consumption
   terraform init
   terraform fmt -check
   terraform validate
   terraform plan
   ```

   Terraform is configured not to register every Azure provider in the
   subscription. The four commands above register only the providers required
   by this POC. Provider registration can take a few minutes; check with
   `az provider show --namespace Microsoft.App --query registrationState`.

7. Apply only after reviewing the resources and costs:

   ```bash
   terraform apply
   terraform output
   ```

The initial image is a public placeholder so the infrastructure can be learned
and verified without paying for a container registry. For the next deployment
step, publish the application image to GitHub Container Registry or another
registry, set `container_image`, and configure registry credentials only when
the image is private. Azure Container Registry is deliberately not created in
this minimum-cost phase.

The public placeholder listens on port `80`, so the initial variables use
`container_target_port = 80`. When we deploy the repository's FastAPI image,
change this to `8000`, which is the port exposed by `app/Dockerfile`.

## Deploy the real application image

The workflow in
[publish-image.yml](./.github/workflows/publish-image.yml) builds
`app/Dockerfile` and publishes it to GitHub Container Registry (GHCR). It uses
the GitHub Actions token automatically; no personal access token is stored in
the repository.

To use it:

1. Commit and push the repository to `main`.
2. Open GitHub **Actions** and run **Publish demo application image** if the
   push workflow did not run automatically.
3. Open the published package in GitHub and change its visibility to **Public**.
   This is a one-time manual step because a new GHCR package is private by
   default. A public package lets the cheapest Container App configuration
   pull the image without adding registry credentials.
4. Add this to your local ignored `terraform.tfvars`:

   ```hcl
   container_image      = "ghcr.io/mariambodokia/smokemonitor-demo:latest"
   container_target_port = 8000
   ```

5. Apply the image change:

   ```bash
   terraform plan
   terraform apply
   ```

6. Verify the deployed application:

   ```bash
   APP_URL=$(terraform output -raw app_url)
   curl --fail "$APP_URL/health"
   BASE_URL="$APP_URL" pytest ../../smoke-tests
   ```

The only manual action in this phase is changing the GHCR package visibility.
It is required because a private image needs additional Azure registry
credentials, which we intentionally avoid until the minimum-cost path works.

When finished experimenting:

```bash
terraform destroy
```

This matters because Container Apps, Log Analytics ingestion, and any Jenkins
VM can create charges. Container Apps can scale to zero, but other resources
still need cost monitoring. The Terraform budget is set to
$150/month to leave approximately $50 of the $200 learning budget as safety
margin. Azure budgets send alerts; they do not stop consumption automatically.

## Minimum-cost architecture

The first Azure deployment intentionally creates only:

- one resource group;
- one consumption-based Container Apps environment;
- one Container App with zero minimum replicas;
- one short-retention Log Analytics workspace;
- one resource-group cost budget.

There is no custom VNet, NAT gateway, private endpoint, VM, Key Vault, or Azure
Container Registry yet. These are valid future additions, but they are not
needed to learn the application and smoke-test workflow. A custom VNet should
be added only when the application must reach private services, restrict
ingress, or meet a specific network/data-residency requirement. At that point,
we can add it as a deliberate architecture change and re-check pricing.

Jenkins will be deployed into a separate resource group from the application.
Set `enable_jenkins = true` only when we add the Jenkins VM and its networking.
This keeps Jenkins infrastructure, cost reporting, access policies, and
deletion independent from the application environment.

## Region choice

The original `eastus` value was only an example. The default is now
`westeurope` because it is generally a better latency choice for users in
Europe or Georgia. It is not guaranteed to be the cheapest region: before
applying, compare `westeurope`, `northeurope`, and `eastus` in the [Azure
Pricing Calculator](https://azure.microsoft.com/pricing/calculator/), and
confirm that the required Container Apps capacity is available. Use one region
for this POC unless a service is unavailable there.

## CI/CD responsibilities

- GitHub Actions validates code and Terraform on pull requests.
- A later protected GitHub Actions workflow will build and publish the image
  and apply Terraform after approval.
- Jenkins runs browser smoke tests against the deployed URL, retries a failed
  test up to two additional times, and archives JUnit and Playwright evidence.

This split is intentional: GitHub Actions provisions infrastructure and Jenkins
performs continuous smoke validation. Do not store Azure passwords,
service-principal keys, or admin tokens in this repository. Use GitHub OIDC,
managed identity, or a secret manager when deployment automation is added.
