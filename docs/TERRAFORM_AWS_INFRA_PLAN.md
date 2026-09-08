# Terraform AWS Infra — Action Plan

Add `killakam3084/terraform` as a submodule of this repo to house Terraform config for
provisioning small-footprint infrastructure in the personal AWS account. No real AWS
resources are created by Terraform this round — the S3 state bucket and dedicated IAM
user are bootstrapped manually via the AWS console, avoiding the chicken-and-egg problem
of Terraform managing the bucket its own backend depends on.

## Decisions

- Scope: submodule + scaffolding only. No real AWS resources defined yet.
- State backend: S3, **partial backend config** (`backend "s3" {}` empty in code, real
  bucket/key/region supplied via gitignored `backend.hcl` at
  `terraform init -backend-config=backend.hcl` time). A checked-in `backend.hcl.example`
  documents the required keys. This avoids hardcoding a bucket name before it exists.
- Locking: native S3 lockfile (`use_lockfile = true`, requires Terraform >= 1.11) — no
  DynamoDB table.
- S3 bucket + dedicated IAM user: created manually via AWS console (out of band, not
  Terraform-managed pre-bootstrap). Bucket needs versioning, default encryption, and
  block public access enabled.
- AWS auth for local/manual runs: dedicated IAM user's keys stored in a new Infisical
  project (`terraform`), following the existing certrenew/rarclean/rss-curator pattern
  (`/mnt/cell_block_d/apps/terraform/.env` with INFISICAL_TOKEN/PROJECT_ID/ENV/DOMAIN).
- Where plan/apply runs: manually from inside the provisioner container on the NAS (via
  new Makefile targets), reviewed before apply. No auto-apply.
- CI (GitHub Actions in the terraform repo): static checks only for now —
  `terraform fmt -check -recursive`, `terraform init -backend=false`,
  `terraform validate`, `tflint`. No plan/apply automation yet.
- Future/deferred: CI-driven plan/apply via OIDC federation (no stored keys) once the
  backend + workflow are proven out.
- `main.tf` intentionally omitted until the first real resource is added.

## Steps

### Phase A — scaffold the new `terraform` repo (currently empty, no commits)

1. Clone `git@github.com:killakam3084/terraform.git` to a local working dir.
2. Add scaffolding files:
   - `README.md` — purpose, manual bootstrap prerequisites, init instructions, how it's
     run (via truenas Makefile from provisioner), note on future OIDC CI follow-up.
   - `.gitignore` — ignore `.terraform/`, `*.tfstate`, `*.tfstate.backup`, `crash.log*`,
     `override.tf*`, `backend.hcl`; do **not** ignore `.terraform.lock.hcl`.
   - `versions.tf` — `required_version = ">= 1.11.0"`,
     `required_providers { aws = { source = "hashicorp/aws", version = "~> 5.0" } }`.
   - `backend.tf` — empty `backend "s3" {}` block (partial config).
   - `backend.hcl.example` — documents required keys: `bucket`,
     `key = "terraform/state/terraform.tfstate"`, `region`, `use_lockfile = true`.
   - `providers.tf` — `provider "aws" { region = var.aws_region }` + default_tags
     (Project, ManagedBy).
   - `variables.tf` — `aws_region` variable.
   - `.github/workflows/ci.yml` — checkout, `hashicorp/setup-terraform`,
     `terraform fmt -check -recursive`, `terraform init -backend=false`,
     `terraform validate`, `terraform-linters/setup-tflint` + `tflint --init && tflint`.
   - `CHANGELOG.md` — Keep a Changelog format, initial entry "Initial scaffolding".
3. Commit (`chore: initial terraform scaffolding`) and push to `main`.

### Phase B — wire submodule into `truenas` parent repo (depends on Phase A)

4. `git submodule add git@github.com:killakam3084/terraform.git terraform`.
5. Update [`Makefile`](../Makefile):
   - Add `terraform` to the submodule loop list in the `pull` target.
   - Add `TERRAFORM_DIR := $(REPO_DIR)terraform` and `TERRAFORM_INFISICAL_PROJECT_ID`
     variables.
   - Add `terraform-plan` / `terraform-apply` targets using
     `terraform -chdir=$(TERRAFORM_DIR) plan|apply` wrapped in the existing
     `infisical-run` macro.
   - Update `.PHONY` list.
6. Update [`README.md`](../README.md):
   - Add `terraform` row to the Submodules table.
   - Add `terraform-plan` / `terraform-apply` rows to the Make Targets table.
   - Short new "Terraform / AWS Infra" section linking to `terraform/README.md`.
7. Commit (`feat: add terraform submodule for AWS infra provisioning`).

## Manual prerequisites (user-performed, not agent-executable)

1. Create S3 bucket via AWS console (versioning, default encryption, block public
   access) — needed to fill in the real `backend.hcl` (gitignored, not committed).
2. Create dedicated IAM user via AWS console with a least-privilege policy scoped to
   what Terraform will manage; generate access keys.
3. Create new Infisical project (`terraform`) + service token (never-expiring, per
   existing pattern); store the IAM user's AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY;
   create `/mnt/cell_block_d/apps/terraform/.env` on the NAS with
   INFISICAL_TOKEN/PROJECT_ID/ENV=prod/DOMAIN.
4. Fill in `TERRAFORM_INFISICAL_PROJECT_ID` in the Makefile once step 3's project ID is
   known.

## Verification

1. `git submodule status` in the truenas repo shows `terraform` initialized and pinned.
2. In the terraform repo: `terraform fmt -check -recursive`,
   `terraform init -backend=false`, `terraform validate` all pass locally before
   pushing.
3. GitHub Actions CI on the terraform repo goes green on first push.
4. `make -n terraform-plan` from the truenas repo shows the expected command wiring.
5. Manual end-to-end (after prerequisites done): `make terraform-plan` from the
   provisioner successfully runs `terraform init -backend-config=backend.hcl` + `plan`
   against the real bucket with no resources (empty plan).

## Further considerations

1. Default AWS region for `variables.tf` — recommend matching wherever your other AWS
   resources already live; confirm before Phase A.
2. IAM policy scope for the dedicated user — start narrow (state bucket + first real
   resource), expanding incrementally rather than broad `AdministratorAccess`.
