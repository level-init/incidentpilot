output "privilege_class_role_arns" {
  description = "Map of privilege class → IAM role ARN (annotate SA for IRSA)."
  value       = { for k, r in aws_iam_role.privilege_class : k => r.arn }
}

output "irsa_enabled" {
  description = "Whether OIDC federated trust is configured."
  value       = local.irsa_enabled
}

output "privilege_class_namespaces" {
  description = "Namespace map used for IRSA subjects."
  value       = var.privilege_class_namespaces
}

output "privilege_class_service_accounts" {
  description = "ServiceAccount name map."
  value       = var.privilege_class_service_accounts
}
