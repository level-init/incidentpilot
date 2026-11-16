output "eks_cluster_role_arn" {
  description = "EKS control plane role ARN."
  value       = aws_iam_role.eks_cluster.arn
}

output "eks_node_role_arn" {
  description = "EKS managed node role ARN."
  value       = aws_iam_role.eks_node.arn
}

output "privilege_class_role_arns" {
  description = "Map of privilege class → IAM role ARN (IRSA wired in O3)."
  value       = { for k, r in aws_iam_role.privilege_class : k => r.arn }
}
