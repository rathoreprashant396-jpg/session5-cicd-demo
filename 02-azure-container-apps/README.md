# Branch 2 — Azure Container Apps (the production factory)

> **Where we are in the journey:** Hugging Face got our idea live fast. Now we move it
> to a cloud built for scale, control, and reliability. 


> In this hands-on we deploy the **app** (Container Apps + ACR). The right-hand
> concepts (AI Foundry, Blob, Monitor, RBAC) are the production pieces you'd add as the
> app grows — see [best practices](../docs/hf-vs-azure.md#best-practices).

## The fast path — one script

```powershell
# Windows PowerShell
az login
./deploy.ps1
```

```bash
# macOS / Linux
az login
./deploy.sh
```

The script does all 6 steps below, reads `GOOGLE_API_KEY` from
`../../../module3_agents/.env`, injects it as a **Container App secret**, prints your
live URL, and reminds you to tear down. The rest of this README explains each step so
you understand what the script automates.

## Step 1 — Install the Azure CLI (`az`)

**Windows (PowerShell, as Administrator):**
```powershell
Invoke-WebRequest -Uri https://aka.ms/installazurecliwindows -OutFile AzureCLI.msi
Start-Process msiexec.exe -ArgumentList '/I AzureCLI.msi /quiet' -Wait
```

**macOS (Homebrew):**
```bash
brew install azure-cli
```

Verify, then log in and add the Container Apps extension:
```bash
az version
az login
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ContainerRegistry
```

> ℹ️ New subscriptions start with most **resource providers** unregistered. The three
> commands above enable Container Apps, its logging, and ACR. Registration is
> asynchronous — if a later step fails with `MissingSubscriptionRegistration`, wait a
> minute and retry (check progress with `az provider show -n <namespace> --query registrationState`).

## Step 2 — Create a resource group (the one thing teardown deletes)

```bash
az group create --name genai-session4-rg --location centralindia
```
A **resource group** is a labelled box that holds related resources. Everything we
create goes in here so cleanup is a single `az group delete`. Pick a **location** near
your users (`centralindia`, `eastus`, `westeurope`, …) — same idea as the PDF's region.

## Step 3 — Create the Container Registry (ACR) and build the image

```bash
az acr create --resource-group genai-session4-rg --name cnacrdemo1 --sku Basic --admin-enabled true

# Build in the cloud straight from the ../app folder (always produces amd64,
# so no Apple-Silicon architecture headaches like the PDF hit on GCP):
az acr build --registry cnacrdemo1 --image genai-app:latest ../app
```
`Basic` is the cheapest SKU. `az acr build` = Cloud Build's equivalent: it builds and
stores the image without you running Docker locally.

> 📛 **Registry names are globally unique across ALL of Azure** (they become
> `<name>.azurecr.io`). Don't copy `cnacrdemo1` literally — pick your own, e.g.
> `cnacr` + your initials + 3 digits, and use it consistently in Steps 3 and 5.

> ⚠️ **Got `TasksOperationsNotAllowed`?** ACR Tasks (the service behind `az acr build`)
> is **disabled on free-trial and Azure-for-Students subscriptions** — no support ticket
> needed. Build the image locally with Docker (exactly like Session 3) and push it
> (replace `cnacrdemo1` with **your** registry name):
> ```bash
> az acr login --name cnacrdemo1
> docker build --platform linux/amd64 -t cnacrdemo1.azurecr.io/genai-app:latest ../app
> docker push cnacrdemo1.azurecr.io/genai-app:latest
> ```
> (`--platform linux/amd64` matters on Apple Silicon — Azure runs amd64 containers.)
> `deploy.ps1` / `deploy.sh` do this fallback automatically if the cloud build is refused.

> 🕑 **`az acr login` / `docker login` hangs or times out?** Work down this list:
> 1. **Is the Docker engine actually running?** `docker version` must print a
>    **Server** section. If it hangs or errors, start Docker Desktop and wait for the
>    whale icon to go steady; on Windows also try `wsl --shutdown`, then reopen Docker Desktop.
> 2. **Broken Docker credential helper** (very common hang): open
>    `%USERPROFILE%\.docker\config.json` (`~/.docker/config.json` on macOS) and delete
>    the `"credsStore": ...` line, then retry the login.
> 3. **Network is blocking the registry**: `curl https://cnacrdemo1.azurecr.io/v2/`
>    should instantly return a small `401` JSON. If *that* times out, the campus
>    Wi-Fi / VPN / proxy is blocking it — switch to a phone hotspot and retry.

## Step 4 — Create the Container Apps environment

```bash
az containerapp env create --name genai-env --resource-group genai-session4-rg --location centralindia
```
The **environment** is the shared boundary (networking + logging) your apps run in.

## Step 5 — Deploy the app (scale-to-zero, minimal size)

```bash
az containerapp create --name genai-app --resource-group genai-session4-rg --environment genai-env --image cnacrdemo1.azurecr.io/genai-app:latest --registry-server cnacrdemo1.azurecr.io --target-port 8000 --ingress external --min-replicas 0 --max-replicas 5 --cpu 0.5 --memory 1.0Gi --secrets gemini-api-key=<YOUR_GEMINI_API_KEY> --env-vars GEMINI_API_KEY=secretref:gemini-api-key
```
What the flags mean:
- `--ingress external` → public HTTPS URL (like Cloud Run's `--allow-unauthenticated`).
- `--target-port 8000` → must match the port the app listens on (the Dockerfile's `$PORT`).
- `--min-replicas 0` → **scale to zero**: no traffic = no charge.
- `--secrets` + `secretref:` → the key is stored as a managed secret and referenced by
  the env var, so it's **never baked into the image or printed**.

## Step 6 — Test & monitor

```bash
FQDN=$(az containerapp show --name genai-app --resource-group genai-session4-rg --query properties.configuration.ingress.fqdn -o tsv)
curl https://$FQDN/health          # -> {"status":"healthy","api_key_configured":true}
```
Open `https://$FQDN/docs` for Swagger. Stream logs (Azure Monitor / Log Analytics):
```bash
az containerapp logs show --name genai-app --resource-group genai-session4-rg --follow
```

## Step 7 — CLEAN UP (do not skip)

```powershell
./teardown.ps1     # Windows
```
```bash
./teardown.sh      # macOS / Linux
```
Both run `az group delete --name genai-session4-rg --yes --no-wait`, removing the
Container App, environment, Log Analytics workspace, and ACR **in one shot**.

## Next — CI/CD (git push → auto-redeploy)

This is exactly what Session 5 is about: the workflows in
[`../.github/workflows/`](../.github/workflows/) rebuild and redeploy on every push
to `main` — the same "just push again" experience as Hugging Face, but for
production. The [Session 5 README](../README.md) walks through the secrets and
setup step by step.