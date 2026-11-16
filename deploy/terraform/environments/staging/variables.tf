variable "aws_region" {
  description = "AWS region for the staging shape."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Resource name prefix (globally unique for S3)."
  type        = string
  default     = "ip-staging"
}

variable "vpc_cidr" {
  description = "VPC CIDR."
  type        = string
  default     = "10.40.0.0/16"
}

variable "azs" {
  description = "AZs for Multi-AZ staging shape."
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs."
  type        = list(string)
  default     = ["10.40.0.0/24", "10.40.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs."
  type        = list(string)
  default     = ["10.40.10.0/24", "10.40.11.0/24"]
}

variable "kubernetes_version" {
  description = "EKS version."
  type        = string
  default     = "1.29"
}

variable "db_username" {
  description = "RDS master username."
  type        = string
  default     = "ip_migrator"
}

variable "enable_expensive_resources" {
  description = <<-EOT
    When false (default), only IAM + Secrets skeleton modules are planned for
    cheap validation. Set true intentionally before applying VPC/EKS/RDS/S3 —
    O1 does not authorize unreviewed expensive prod applies.
  EOT
  type        = bool
  default     = false
}
