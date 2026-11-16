output "cluster_name" {
  description = "EKS cluster name."
  value       = aws_eks_cluster.this.name
}

output "cluster_arn" {
  description = "EKS cluster ARN."
  value       = aws_eks_cluster.this.arn
}

output "cluster_endpoint" {
  description = "EKS API endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 CA data for kubeconfig."
  value       = aws_eks_cluster.this.certificate_authority[0].data
  sensitive   = true
}

output "oidc_issuer_url" {
  description = "OIDC issuer URL (IRSA / O3)."
  value       = try(aws_eks_cluster.this.identity[0].oidc[0].issuer, null)
}

output "node_group_arn" {
  description = "Default managed node group ARN."
  value       = aws_eks_node_group.default.arn
}
