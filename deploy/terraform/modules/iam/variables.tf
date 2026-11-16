variable "name_prefix" {
  description = "Name prefix for IAM roles."
  type        = string
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
