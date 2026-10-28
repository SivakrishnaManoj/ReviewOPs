variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "name" {
  type    = string
  default = "reviewops-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "Use a short lowercase name with hyphens."
  }
}

variable "github_oidc_subject" {
  type        = string
  description = "Exact sub claim from the OIDC identity workflow on main. Never use a wildcard."
  validation {
    condition     = can(regex("^repo:SivakrishnaManoj(@[0-9]+)?/ReviewOPs(@[0-9]+)?:ref:refs/heads/main$", var.github_oidc_subject))
    error_message = "The subject must identify this exact repository's main branch."
  }
}

variable "existing_github_oidc_provider_arn" {
  type        = string
  default     = null
  description = "Use an existing account-level GitHub OIDC provider when one already exists."
}

variable "enable_service" {
  type        = bool
  default     = false
  description = "Enable only after an application image has been pushed to ECR. Creates billable compute and ALB resources."
}

variable "initial_image" {
  type        = string
  default     = ""
  description = "ECR image URI pinned by sha256 digest for the first deployment. Subsequent images are owned by CI/CD."
  validation {
    condition     = var.initial_image == "" || can(regex("@sha256:[a-f0-9]{64}$", var.initial_image))
    error_message = "Use an immutable image digest, not a mutable tag."
  }
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
  description = "Optional public subnets in one VPC, at least two AZs. Empty uses the account's default VPC."
  validation {
    condition     = length(var.subnet_ids) == 0 || length(var.subnet_ids) >= 2
    error_message = "Provide at least two subnets or leave the list empty."
  }
}

variable "container_secret_arns" {
  type        = map(string)
  default     = {}
  description = "Optional environment-variable names mapped to existing Secrets Manager ARNs. Values never enter Terraform."
  validation {
    condition     = alltrue([for key in keys(var.container_secret_arns) : contains(["DATABASE_URL", "DEMO_API_KEY"], key)])
    error_message = "Supported secrets: DATABASE_URL and DEMO_API_KEY."
  }
}
