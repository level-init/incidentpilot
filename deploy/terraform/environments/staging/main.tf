locals {
  common_tags = {
    Project     = "incidentpilot"
    Environment = "staging"
    ManagedBy   = "terraform"
    Epic        = "O1-O3"
  }
}

module "iam" {
  source = "../../modules/iam"

  name_prefix = var.name_prefix
  tags        = local.common_tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix = var.name_prefix
  db_username = var.db_username
  tags        = local.common_tags
}

# Expensive staging-shape stack — gated so `terraform validate` / casual plans
# do not imply an unreviewed apply (O1 out of scope).
module "vpc" {
  count  = var.enable_expensive_resources ? 1 : 0
  source = "../../modules/vpc"

  name_prefix          = var.name_prefix
  cidr_block           = var.vpc_cidr
  azs                  = var.azs
  public_subnet_cidrs  = var.public_subnet_cidrs
  private_subnet_cidrs = var.private_subnet_cidrs
  tags                 = local.common_tags
}

module "eks" {
  count  = var.enable_expensive_resources ? 1 : 0
  source = "../../modules/eks"

  name_prefix        = var.name_prefix
  kubernetes_version = var.kubernetes_version
  subnet_ids         = module.vpc[0].private_subnet_ids
  cluster_role_arn   = module.iam.eks_cluster_role_arn
  node_role_arn      = module.iam.eks_node_role_arn
  tags               = local.common_tags
}

data "tls_certificate" "eks_oidc" {
  count = var.enable_expensive_resources ? 1 : 0
  url   = module.eks[0].oidc_issuer_url
}

resource "aws_iam_openid_connect_provider" "eks" {
  count = var.enable_expensive_resources ? 1 : 0

  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.eks_oidc[0].certificates[0].sha1_fingerprint]
  url             = module.eks[0].oidc_issuer_url

  tags = local.common_tags
}

# O3: privilege-class IRSA roles (cheap IAM even when EKS gated off).
module "irsa" {
  source = "../../modules/irsa"

  name_prefix       = var.name_prefix
  oidc_provider_arn = try(aws_iam_openid_connect_provider.eks[0].arn, "")
  oidc_issuer_url   = try(module.eks[0].oidc_issuer_url, "")
  tags              = local.common_tags
}

module "s3" {
  count  = var.enable_expensive_resources ? 1 : 0
  source = "../../modules/s3"

  name_prefix   = var.name_prefix
  force_destroy = true
  tags          = local.common_tags
}

module "rds" {
  count  = var.enable_expensive_resources ? 1 : 0
  source = "../../modules/rds"

  name_prefix         = var.name_prefix
  vpc_id              = module.vpc[0].vpc_id
  subnet_ids          = module.vpc[0].private_subnet_ids
  allowed_cidr_blocks = [module.vpc[0].cidr_block]
  master_username     = var.db_username
  master_password     = module.secrets.db_master_password
  multi_az            = true
  tags                = local.common_tags
}
