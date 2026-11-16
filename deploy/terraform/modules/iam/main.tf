# Cluster / node roles for EKS. IRSA per privilege class is O3 — no shared admin SA.

data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "eks_cluster" {
  name               = "${var.name_prefix}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "eks_cluster_policy" {
  role       = aws_iam_role.eks_cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_iam_role" "eks_node" {
  name               = "${var.name_prefix}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "eks_worker_node" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy"
}

resource "aws_iam_role_policy_attachment" "eks_cni" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy"
}

resource "aws_iam_role_policy_attachment" "eks_ecr_readonly" {
  role       = aws_iam_role.eks_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

# Placeholder role names for O3 IRSA wiring (created empty; policies attach later).
locals {
  privilege_classes = [
    "api",
    "worker",
    "evidence",
    "remediation",
    "runner",
    "evaluator",
  ]
}

data "aws_iam_policy_document" "irsa_placeholder_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
    # O3 replaces this with OIDC federated trust per SA — no shared admin.
  }
}

resource "aws_iam_role" "privilege_class" {
  for_each = toset(local.privilege_classes)

  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.irsa_placeholder_assume.json
  tags = merge(var.tags, {
    PrivilegeClass = each.key
    IRSA           = "pending-O3"
  })
}
