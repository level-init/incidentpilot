variable "name_prefix" {
  description = "Cluster name prefix (also used as cluster name)."
  type        = string
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.29"
}

variable "subnet_ids" {
  description = "Subnet ids for the control plane / nodes (private preferred)."
  type        = list(string)
}

variable "cluster_role_arn" {
  description = "IAM role ARN for the EKS control plane."
  type        = string
}

variable "node_role_arn" {
  description = "IAM role ARN for managed node groups."
  type        = string
}

variable "endpoint_public_access" {
  description = "Allow public API endpoint (staging often true; tighten later)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
