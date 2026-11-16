variable "name_prefix" {
  description = "Prefix for Secrets Manager secret names."
  type        = string
}

variable "db_username" {
  description = "Postgres master username stored alongside the password."
  type        = string
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
