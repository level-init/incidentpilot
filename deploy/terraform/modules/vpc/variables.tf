variable "name_prefix" {
  description = "Name prefix for VPC resources (e.g. ip-staging)."
  type        = string
}

variable "cidr_block" {
  description = "VPC IPv4 CIDR."
  type        = string
  default     = "10.40.0.0/16"
}

variable "azs" {
  description = "Availability zones for staging shape (Multi-AZ ready)."
  type        = list(string)
}

variable "public_subnet_cidrs" {
  description = "Public subnet CIDRs (one per AZ)."
  type        = list(string)
}

variable "private_subnet_cidrs" {
  description = "Private subnet CIDRs (one per AZ)."
  type        = list(string)
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
