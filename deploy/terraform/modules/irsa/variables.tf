variable "name_prefix" {
  description = "Name prefix for privilege-class IAM roles."
  type        = string
}

variable "oidc_provider_arn" {
  description = "EKS OIDC provider ARN (empty = placeholder trust for validate-only)."
  type        = string
  default     = ""
}

variable "oidc_issuer_url" {
  description = "EKS OIDC issuer URL without trailing slash."
  type        = string
  default     = ""
}

variable "privilege_class_namespaces" {
  description = "Map privilege class → Kubernetes namespace for IRSA subject."
  type        = map(string)
  default = {
    api         = "incidentpilot-system"
    worker      = "incidentpilot-system"
    evidence    = "incidentpilot-system"
    remediation = "incidentpilot-system"
    web         = "incidentpilot-system"
    evaluator   = "incidentpilot-eval"
    runner      = "incidentpilot-eval"
  }
}

variable "privilege_class_service_accounts" {
  description = "Map privilege class → ServiceAccount name."
  type        = map(string)
  default = {
    api         = "incidentpilot-api"
    worker      = "incidentpilot-worker"
    evidence    = "incidentpilot-evidence"
    remediation = "incidentpilot-remediation"
    web         = "incidentpilot-web"
    evaluator   = "incidentpilot-evaluator"
    runner      = "incidentpilot-runner"
  }
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
