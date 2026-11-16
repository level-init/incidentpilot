variable "name_prefix" {
  description = "Name prefix for RDS resources."
  type        = string
}

variable "vpc_id" {
  description = "VPC id for the DB subnet group / SG."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet ids for the DB subnet group."
  type        = list(string)
}

variable "allowed_cidr_blocks" {
  description = "CIDRs allowed to reach Postgres (typically VPC CIDR)."
  type        = list(string)
}

variable "engine_version" {
  description = "PostgreSQL engine version."
  type        = string
  default     = "16.4"
}

variable "instance_class" {
  description = "RDS instance class (staging shape)."
  type        = string
  default     = "db.t4g.medium"
}

variable "allocated_storage" {
  description = "Allocated storage GiB."
  type        = number
  default     = 50
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "incidentpilot"
}

variable "master_username" {
  description = "Master username (password stored in Secrets Manager via secrets module)."
  type        = string
  default     = "ip_migrator"
}

variable "master_password" {
  description = "Master password — pass from secrets module; never commit."
  type        = string
  sensitive   = true
}

variable "multi_az" {
  description = "Multi-AZ for staging reference posture (O11 documents prod)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
