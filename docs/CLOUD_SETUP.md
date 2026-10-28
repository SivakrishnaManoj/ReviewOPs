# AWS setup — S. owns this

Default region: London, `eu-west-2`. This file is a runbook, not a record of deployment.
The scaffold has not been applied to any AWS account.

## 1. Prepare the account and state

Use your own AWS SSO/CLI profile; verify the intended account with:

```sh
aws sts get-caller-identity
```

Install AWS CLI v2 and Terraform 1.13.5 (or a compatible version >=1.10).
Create a dedicated S3 bucket for Terraform state in `eu-west-2`: private, Block Public
Access enabled, versioning enabled, server-side encryption enabled. Keep its name unique.
It is deliberately separate from the dataset bucket and must survive application teardown.
The local Terraform identity needs read/write access to the state key and its `.tflock`.

Copy `infra/backend.hcl.example` to `infra/backend.hcl` and set that bucket's name.
Copy `infra/terraform.tfvars.example` to `infra/terraform.tfvars`.
Both live configuration files are ignored by Git. Do not place secret values in them.

Create an AWS budget alert appropriate to your budget. Alerts are not a hard spending cap.
The application service is initially disabled, and maximum task count is one. Once enabled,
Fargate, an Application Load Balancer, logs, and data storage can incur ongoing charges.

## 2. Obtain the repository's exact OIDC subject

After the scaffold is on `main`, run **Actions → Read OIDC identity → Run workflow → main**.
Copy only the printed `sub` value into `github_oidc_subject` in `terraform.tfvars`.

New GitHub repositories can include immutable numeric owner/repository IDs in `sub`.
Do not copy an old example blindly. The helper prints identity claims, never the token.
This workflow does not use a GitHub environment, so its branch subject matches delivery.
If you later add an environment, update the trust policy to the exact new subject.

If the AWS account already has the GitHub OIDC provider, put its ARN in
`existing_github_oidc_provider_arn`. There can be only one provider for that URL per account.

## 3. Create the foundation

Leave `enable_service = false`, then run from the repository root:

```sh
terraform -chdir=infra init -backend-config=backend.hcl
terraform -chdir=infra plan -out=foundation.tfplan
terraform -chdir=infra apply foundation.tfplan
terraform -chdir=infra output
```

Review the plan before applying. This creates ECR, the private data bucket, logging,
the ECS cluster, OIDC if needed, and scoped roles. It does not create RDS or run containers.
Keep `infra/.terraform.lock.hcl` committed. Never commit the state or the plan file.

## 4. Enable image publishing

In GitHub **Settings → Secrets and variables → Actions → Variables**, add:

| Variable | Value |
| --- | --- |
| `AWS_REGION` | `eu-west-2` |
| `AWS_ROLE_ARN` | Terraform `delivery_role_arn` output |
| `ECR_REPOSITORY` | Terraform `ecr_repository_name` output |
| `AWS_DELIVERY_ENABLED` | `true` |

Leave `ECS_SERVICE_ARN` unset. Run **CI and delivery** manually on `main`, with deployment
unchecked. It tests and publishes an image but cannot update a service yet.
Copy the immutable `...@sha256:...` image URI from the run summary.

The delivery role can push only to the project ECR repository and update only the named
service. It cannot apply Terraform or create arbitrary AWS infrastructure.

## 5. Create the HTTPS service

Set `initial_image` to the published digest URI and `enable_service = true`.
Confirm the region has a default VPC with public subnets across at least two AZs;
otherwise supply suitable `subnet_ids`. The first prototype uses the Express-managed
networking defaults and its own HTTPS endpoint.

```sh
terraform -chdir=infra plan -out=service.tfplan
terraform -chdir=infra apply service.tfplan
terraform -chdir=infra output
```

IAM may need a brief propagation delay after roles are first created. If AWS reports
an assume-role error immediately after provisioning, let propagation complete and rerun
the reviewed plan. Do not broaden IAM permissions to fix propagation.

Add the returned `service_arn` as GitHub variable `ECS_SERVICE_ARN`.
Check the returned HTTPS endpoint and `/healthz`. Database `/readyz` will return 503 until
the cloud database is attached: liveness is intentionally separate from data readiness.

Merge one change to `main` to exercise delivery. The deployment checks both process health
and the exact `build_sha`; inspect the `deployment-...` artifact for image provenance.

## 6. Attach the database and model later

Create RDS PostgreSQL privately in the same VPC. Its database security group should accept
5432 only from the ECS application's security group. Use a separate migration/admin identity
to enable pgvector and apply schema migrations; runtime should use a restricted app user.
Keep TLS enabled in the database connection string.

Store that complete DSN in Secrets Manager and add its ARN under
`container_secret_arns = { DATABASE_URL = "..." }` in Terraform. Use the AWS-managed
Secrets Manager encryption key for this first template; a customer-managed key needs
an additional narrowly scoped KMS decrypt permission. Terraform never reads the secret value.

Run migrations once from a network-connected administrative runner/task, not on every
API startup. The bundled `scripts.migrate` is ready to run with the admin DSN in its
environment. Never expose a private database to the internet to run this command.

With the AI owner, configure one Bedrock model and add its required inference permissions
to the **task role**, not the GitHub delivery role. No inference is enabled by this scaffold.
Before a public AI demo, add the `DEMO_API_KEY` secret (or proper user authentication)
and server-side request/token/step limits. Never bake this key into the frontend bundle.

## Rollback and operations

- CloudWatch log group: `/reviewops/reviewops-demo`; retention is seven days.
- ECS Express manages the load balancer and deployment infrastructure.
- CI updates the image while preserving environment, secrets, and port settings.
- If the new image is stable but its smoke check fails, CI attempts to restore the previous
  image and reports failure. If ECS is still deploying, CI stops without racing it; inspect
  ECS events before intervening. Rollback is best effort and does not reverse schema changes.
- Terraform ignores only the application image field after initial creation, so later
  infrastructure applies do not replace the image selected by CI.
- For a deliberate rollback, use the recorded previous image and its commit SHA with
  `uv run python -m scripts.deploy --service-arn ... --image ... --sha ...` from an
  authorised local session. Then run the application's relevant functional checks.

To pause the demo, set `AWS_DELIVERY_ENABLED=false`, set `enable_service=false`, and review
and apply the Terraform plan. This removes the Express service and its managed resources;
check the AWS console afterwards for retained resources. Data/ECR remain intentionally.
Terraform refuses to delete non-empty dataset buckets and ECR repositories. Decide what
to preserve before any full teardown; the state bucket must be retained until cleanup ends.

## Primary documentation

- [ECS Express Mode](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-overview.html)
- [Terraform Express service resource](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/ecs_express_gateway_service)
- [GitHub OIDC subjects](https://docs.github.com/en/actions/reference/security/oidc)
- [AWS authentication action](https://github.com/aws-actions/configure-aws-credentials)
- [pgvector](https://github.com/pgvector/pgvector)
