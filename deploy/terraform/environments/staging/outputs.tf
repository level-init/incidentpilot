output "iam_eks_cluster_role_arn" {
  description = "EKS cluster role ARN."
  value       = module.iam.eks_cluster_role_arn
}

output "irsa_privilege_class_role_arns" {
  description = "Privilege-class IAM roles for SA IRSA annotations (O3)."
  value       = module.irsa.privilege_class_role_arns
}

output "irsa_enabled" {
  description = "True when EKS OIDC provider is wired into IRSA trusts."
  value       = module.irsa.irsa_enabled
}

output "secrets_arns" {
  description = "Secrets Manager ARNs."
  value       = module.secrets.secret_arns
}

output "vpc_id" {
  description = "VPC id when enable_expensive_resources=true."
  value       = try(module.vpc[0].vpc_id, null)
}

output "eks_cluster_name" {
  description = "EKS cluster name when enabled."
  value       = try(module.eks[0].cluster_name, null)
}

output "eks_oidc_issuer_url" {
  description = "EKS OIDC issuer when enabled."
  value       = try(module.eks[0].oidc_issuer_url, null)
}

output "rds_endpoint" {
  description = "RDS endpoint when enabled."
  value       = try(module.rds[0].db_endpoint, null)
}

output "s3_bucket_ids" {
  description = "S3 bucket ids when enabled."
  value       = try(module.s3[0].bucket_ids, null)
}

output "enable_expensive_resources" {
  description = "Whether the expensive staging stack modules are included."
  value       = var.enable_expensive_resources
}
