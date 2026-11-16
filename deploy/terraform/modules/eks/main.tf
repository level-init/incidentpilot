# EKS control plane skeleton (O1). Node groups / add-ons land with O8.

resource "aws_eks_cluster" "this" {
  name     = var.name_prefix
  role_arn = var.cluster_role_arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_public_access
  }

  enabled_cluster_log_types = [
    "api",
    "audit",
    "authenticator",
  ]

  tags = merge(var.tags, {
    Name = var.name_prefix
  })
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "${var.name_prefix}-default"
  node_role_arn   = var.node_role_arn
  subnet_ids      = var.subnet_ids

  scaling_config {
    desired_size = 2
    max_size     = 4
    min_size     = 1
  }

  instance_types = ["t3.medium"]
  capacity_type  = "ON_DEMAND"

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-default-ng"
  })

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }
}
