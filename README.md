# SmokeMonitor POC

This repository is the reproducible proof of concept for the workflow in
[FlowChart.drawio](./FlowChart.drawio). It contains the first vertical slice:

- a deliberately fault-injectable FastAPI commerce application;
- ten Playwright smoke tests covering health, catalog, product details,
  checkout, orders, admin access, and failure handling;
- a real Jenkins LTS VM with the official Jenkins Monitor Pro plugin;
- Terraform for a minimal Azure Container Apps environment and Log Analytics;
- a GitHub Actions validation pipeline.
- an optional SmokeMonitor result API for machine-readable evidence.

The screenshot's product is **Monitor Pro for Jenkins**. It is installed in
Jenkins itself and reads Jenkins views/jobs through the Jenkins REST API; the
FastAPI service below is not a replacement for that plugin.

SmokeMonitor is implemented as a FastAPI service in
[smokemonitor/](./smokemonitor). It accepts normalized Jenkins results at
`POST /api/results`, parses JUnit XML, exposes run details through
`/api/runs/{run_id}`, and displays a live dashboard at `/`. Azure uses a
low-cost, durable Azure Table Storage backend; local Docker Compose uses SQLite.

After Azure provisioning, its URL is available with:

```bash
terraform -chdir=infra/terraform output -raw smokemonitor_url
```

The Azure deployment workflow builds and publishes both `app/` and
`smokemonitor/`, updates both Container Apps, and checks the monitor health
endpoint. Terraform also provisions the monitor's Azure Storage account and
table, so test history survives Container Apps restarts and scale-to-zero.
Add a GitHub repository secret named `SMOKEMONITOR_TOKEN` with the same value as
the Terraform `admin_token` to publish GitHub Actions smoke results. Without
that secret, deployment still works but the workflow deliberately skips result
publication.

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

The app image is stored in Azure Container Registry (Basic SKU). This adds a
small predictable registry charge, but avoids GHCR visibility and anonymous-pull
problems. Terraform configures the Container App to authenticate to this
registry using its generated admin credentials; those credentials are stored in
Terraform state, which must remain private.

The initial `container_image = ""` setting means Terraform uses the public
placeholder image. After the first apply creates the registry, build and push
the real image:

```bash
REGISTRY=$(terraform output -raw registry_login_server)
REGISTRY_NAME=$(terraform output -raw registry_name)
az acr login --name "$REGISTRY_NAME"
docker build -t "$REGISTRY/smokemonitor-demo:latest" ../../app
docker push "$REGISTRY/smokemonitor-demo:latest"
```

Then set this in `terraform.tfvars`:

```hcl
container_image       = "YOUR_REGISTRY_LOGIN_SERVER/smokemonitor-demo:latest"
container_target_port = 8000
```

Run `terraform apply` again. The Container App will then pull the private image
from ACR using the registry credentials Terraform configured.

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

## Real Jenkins and Monitor Pro

Terraform creates Jenkins in the separate `smokemonitor-jenkins` resource
group, in Sweden Central, while the demo application remains in North Europe.
The VM uses a regionally available `Standard_D2ads_v5` size because this
subscription has no B-series capacity in the original region. Ports 22 and
8080 are restricted to `jenkins_allowed_cidr`.

Get the Jenkins URL and initial setup password:

```bash
terraform -chdir=infra/terraform output -raw jenkins_url
ssh -i ~/.ssh/smokemonitor_jenkins azureuser@$(terraform -chdir=infra/terraform output -raw jenkins_public_ip) \
  'sudo cat /opt/jenkins_home/secrets/initialAdminPassword'
```

Open the URL, paste the password, complete the Jenkins setup wizard, and
create a Pipeline job pointing at this repository's `Jenkinsfile`. The
`monitor-pro:1.0.9` plugin is installed in Jenkins during VM bootstrap. After
Jenkins restarts, the **Monitor Pro** entry appears in the Jenkins left menu.
The plugin is an old 2018 release, so its compatibility is intentionally
validated on this real Jenkins instance rather than hidden behind a custom UI.

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

Jenkins and the real Monitor Pro plugin run in a separate
`smokemonitor-jenkins` resource group in Sweden Central, while the application
remains in North Europe. This deliberately demonstrates a cross-region setup.
The VM is a low-cost Standard_B1s with
a persistent OS disk. Terraform restricts ports 22 and 8080 to
`jenkins_allowed_cidr`; do not use `0.0.0.0/0` except for a short diagnostic.
The plugin is the official `monitor-pro:1.0.9` release shown in the original
diagram. It is an old plugin (released in 2018), so it is installed explicitly
and should be validated during the Jenkins first-run setup rather than
represented by a custom replacement dashboard.

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
- [deploy-azure.yml](./.github/workflows/deploy-azure.yml) builds the app image,
  pushes it to the Terraform-created ACR, updates Container Apps, and runs the
  smoke tests against the deployed URL.
- Jenkins runs browser smoke tests against the deployed URL, retries a failed
  test up to two additional times, and archives JUnit and Playwright evidence.

This split is intentional: GitHub Actions provisions infrastructure and Jenkins
performs continuous smoke validation. Do not store Azure passwords,
service-principal keys, or admin tokens in this repository. Use GitHub OIDC,
managed identity, or a secret manager when deployment automation is added.

## One-time GitHub Actions Azure setup

The deployment workflow uses GitHub OIDC, so no Azure password is stored in
GitHub. An Azure administrator must create an Entra application/service
principal with a federated credential for this repository and grant it:

- `AcrPush` on the ACR;
- `Contributor` on the application resource group, so it can update the
  Container App.

Add these repository secrets under **Settings → Secrets and variables →
Actions**:

```text
AZURE_CLIENT_ID
AZURE_TENANT_ID
AZURE_SUBSCRIPTION_ID
```

After those three secrets exist, pushing a change to `main` automatically builds
the app, deploys it, and runs the smoke suite. Terraform remains responsible
for creating and changing the Azure infrastructure; the workflow is responsible
for routine application releases.
