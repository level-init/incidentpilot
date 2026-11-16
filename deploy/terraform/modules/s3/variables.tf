variable "name_prefix" {
  description = "Prefix for bucket names (globally unique suffix recommended)."
  type        = string
}

variable "force_destroy" {
  description = "Allow destroy of non-empty buckets (staging only)."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Common tags."
  type        = map(string)
  default     = {}
}
