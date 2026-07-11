# Session 5 — Automating Deployment with CI/CD

> **Where we are in the journey:** In Session 4 you deployed the GenAI app to Azure
> *manually* — like a chef carrying every dish to the table personally. It worked, but
> every prompt tweak meant rebuild → push → deploy → check logs, by hand, every time.
> This session installs the **robotic waiters**: pipelines that test, package, and
> ship every change automatically the moment you `git push`.

## What's in this folder

| Path | What it is |
|------|-----------|
| [`app/`](app/) | The same FastAPI + Gemini app from Sessions 3–4, now with **unit tests** ([`test_main.py`](app/test_main.py)) |
| [`.github/workflows/01-ci.yaml`](.github/workflows/01-ci.yaml) | **CI only** — format check + lint + tests + Docker build on every push/PR. Nothing ships. |
| [`.github/workflows/02-deploy-azure.yaml`](.github/workflows/02-deploy-azure.yaml) | **Full CI/CD** — test → build → verify → push to ACR → deploy to Azure Container Apps |
| [`02-azure-container-apps/`](02-azure-container-apps/) | Session 4's one-shot provisioning scripts — you run `deploy.ps1`/`deploy.sh` **once** to create the Azure resources the pipeline updates forever after |
| [`.flake8`](.flake8) | flake8 lint rules — the same ones CI and your local pre-commit hook enforce |
| [`.pre-commit-config.yaml`](.pre-commit-config.yaml) | Runs black (auto-fix) then flake8 (lint) on `app/` before every local commit, so failures never reach CI |

## CI vs CD in one table (the restaurant, again)

| Concept | Analogy | What it does | Why GenAI needs it |
|---------|---------|--------------|--------------------|
| **Continuous Integration (CI)** | Kitchen taste-tester | Every change is tested immediately; broken code is caught in minutes | Prompts, model versions, and configs change 10–20× a day |
| **Continuous Deployment (CD)** | Automated serving robot | Every *approved* change ships to production automatically | Prompt fixes and model swaps need instant, consistent rollout |

## Anatomy of a workflow — 90% of GitHub Actions in 3 ideas

Open [`01-ci.yaml`](.github/workflows/01-ci.yaml) side-by-side with this list:

1. **Trigger** (`on:`) — *"start cooking when ingredients arrive."* Ours fires on
   every push and pull request to `main`.
2. **Jobs** — self-contained clean VMs. `01-ci.yaml` has two (`test`, then
   `docker-build` via `needs:`) to show sequencing; `02-deploy-azure.yaml` uses one
   combined job so build and deploy share the same runner and image.
3. **Steps** — recipe lines executed top to bottom: checkout → install → format check →
   lint → test → build → deploy. Each one deterministic, each one visible in the Actions log.

## Linting: black + flake8 in CI + a local pre-commit hook

`01-ci.yaml`'s `test` job runs `black --check` then `flake8 app/` right after
installing dependencies — before tests or the Docker build even start, so a
style/error problem fails fast and cheap. flake8 only *reports* problems (it has
no auto-fix); black is the one that actually rewrites code — reflowing long
lines, quotes, spacing — so most formatting issues never reach a flake8 failure
in the first place. Rules live in [`.flake8`](.flake8) (100-char line length,
matching black's `--line-length=100`; `__pycache__`, `.pytest_cache`, and the
Azure scripts folder excluded).

To catch — and auto-fix — the same issues **before** they ever reach GitHub,
install the pre-commit hook once per clone:

```bash
pip install -r app/requirements-dev.txt   # installs black + flake8 + pre-commit
pre-commit install                        # wires the hook into .git/hooks/pre-commit
```

From then on, every `git commit` runs black (rewriting staged files in `app/` if
needed) and then flake8 against them. If black changes anything, the commit is
blocked so you can review the diff — `git add` the reformatted files and commit
again. Run either step on demand without committing:

```bash
pre-commit run --all-files
```

## The PDF deploys to GCP — we deploy to Azure. Same recipe, different kitchen:

| Session 5 PDF (GCP) | This folder (Azure) |
|---------------------|---------------------|
| `google-github-actions/auth` + `GCP_SA_KEY` | `azure/login` + `AZURE_CREDENTIALS` |
| Service account JSON key | Service principal JSON (the same "robot employee" idea) |
| Artifact Registry (`*.pkg.dev`) | Azure Container Registry (`*.azurecr.io`) |
| `gcloud auth configure-docker` | `az acr login` |
| `gcloud run deploy` | `az containerapp update` |

> 💡 **Why `docker build` on the runner instead of `az acr build`?** Remember
> Session 4's `TasksOperationsNotAllowed` error — ACR Tasks is disabled on
> free-trial/student subscriptions. The GitHub runner is a free amd64 build machine,
> so the pipeline builds there and only *pushes* to ACR. Every subscription type can
> do that.

---

# Hands-on: make your app deploy itself

## Step 0 — Create the GitHub repo (workflows only work from the repo root)

GitHub only reads workflows from `<repo-root>/.github/workflows/`, so **this
`session5` folder must be the root of its own repository**:

```powershell
cd session5
git init -b main
git add .
git commit -m "Session 5: GenAI app + CI/CD pipelines"
gh repo create genai-cicd --private --source . --push   # or add a remote manually
```

The moment this lands on GitHub, the **CI workflow already runs** (green tick =
format check + lint + tests + Docker build passed). The deploy workflow fails
until you finish the steps below — that's expected: it's missing its secrets.

Before your first commit, install the pre-commit hook so formatting/lint issues
are caught and fixed locally instead of in CI (see
[Linting](#linting-black--flake8-in-ci--a-local-pre-commit-hook) above):

```bash
pip install -r app/requirements-dev.txt
pre-commit install
```

## Step 1 — Provision Azure once (the pipeline updates, it doesn't create)

```powershell
az login
cd 02-azure-container-apps
./deploy.ps1        # macOS/Linux: ./deploy.sh
```

📝 **Write down the ACR name it prints at the end** (e.g. `genaiacr48291`) — you
need it for the `ACR_NAME` secret. Session 4's README in that folder explains every
step the script automates.

## Step 2 — Create the deployment "robot employee" (service principal)

The PDF creates a GCP service account with 4 roles; on Azure it's one command —
a **service principal** scoped to *only* our resource group:

```powershell
az ad sp create-for-rbac --name genai-ci --role contributor `
  --scopes /subscriptions/<YOUR-SUBSCRIPTION-ID>/resourceGroups/genai-session4-rg `
  --sdk-auth
```

(Find your subscription id with `az account show --query id -o tsv`. Ignore the
`--sdk-auth` deprecation warning — `azure/login` still consumes this format.)

Copy the **entire JSON output**, from `{` to `}`. This is the vault key — treat it
like a password.

## Step 3 — Stock the vault: GitHub Secrets

GitHub repo → **Settings → Secrets and variables → Actions → New repository secret**, three times:

| Secret name | Value |
|-------------|-------|
| `AZURE_CREDENTIALS` | the entire JSON from Step 2 |
| `ACR_NAME` | your registry name from Step 1, **without** `.azurecr.io` |
| `GEMINI_API_KEY` | your Gemini key from Google AI Studio (used only for the pipeline's smoke test) |

Once stored, a secret can be *used* by workflows but never *seen* again — if a step
ever tries `echo $SECRET`, GitHub prints `***`. Keys stay out of code, out of logs,
out of git history.

## Step 4 — Push a change and watch the robots work

```bash
echo "# testing CI/CD" >> README.md
git add . && git commit -m "Test automated deployment" && git push
```

GitHub repo → **Actions** tab → watch both workflows live. The full journey:

```
1. You push to main
2. GitHub triggers both workflows
3. Runner checks out code onto a clean VM
4. black --check verifies formatting    ← unformatted code stops HERE
5. flake8 lints app/                    ← style/error problems stop HERE
6. Unit tests run                       ← broken code stops HERE
7. Docker image built (tags: commit-hash + latest)
8. Container booted and /health checked ← broken image stops HERE
9. Image pushed to ACR (Azure's container warehouse)
10. az containerapp update points the app at the new commit-hash tag
11. Live /health check on the public URL ← bad deploy fails LOUDLY here
12. Your change is live. You did nothing but `git push`.
```

3–5 minutes later the deploy job's log prints your live URL and Swagger docs link.

Now do what GenAI teams do all day: change the default model or tweak a prompt in
[`app/main.py`](app/main.py), push, and watch it go live with zero manual steps.

## Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Deploy workflow fails at **Azure login** | `AZURE_CREDENTIALS` missing/incomplete — re-paste the *entire* JSON including braces |
| Fails at **Push to ACR** with 401/404 | `ACR_NAME` secret doesn't match the registry `deploy.ps1` created (no `.azurecr.io` suffix!) |
| Fails at **Deploy** with `ResourceNotFound` | You skipped Step 1, or tore the resource group down — run `deploy.ps1` again, update `ACR_NAME` |
| Fails at **Deploy** with authorization error | Service principal scoped to the wrong subscription/resource group — redo Step 2 |
| **Smoke test** fails | The app genuinely doesn't boot — read that step's log; this is CI doing its job |
| Workflows don't appear in the Actions tab | `.github/` isn't at the repo root — redo Step 0 with `session5` as the root |

> The instructor's classroom rule from the PDF applies here too: **most failures are
> secret problems.** Screenshot your three secrets before debugging anything else.

## Clean up (do not skip)

The pipeline keeps the app alive as long as the resource group exists:

```powershell
cd 02-azure-container-apps
./teardown.ps1      # macOS/Linux: ./teardown.sh
```

Optionally delete the service principal too: `az ad sp delete --id <appId from Step 2>`.

## Key takeaways

- **Automation eliminates repetition** — one push runs the entire test-build-deploy chain.
- **Versioning is built in** — every image is tagged with its commit hash; rollback = redeploy an old hash.
- **Testing is mandatory** — failed tests (or a container that won't boot) block deployment automatically.
- **Secrets are secure** — credentials live in GitHub's vault, never in code or logs.
- Your role changes from *operator* to *designer*: you improve the recipe, the robots handle delivery.
