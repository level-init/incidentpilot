output "eks_cluster_role_arn" {
  description = "EKS control plane role ARN."
  value       = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  description = "EKS managed node role ARN."
  value       = aws_iam_role.eks_node.arn
}
