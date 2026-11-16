# O3: one privilege class → one IAM role trusted for one SA (IRSA). No shared admin.

locals {
  privilege_classes = keys(var.privilege_class_service_accounts)
  irsa_enabled      = var.oidc_provider_arn != "" && var.oidc_issuer_url != ""
  oidc_host         = local.irsa_enabled ? replace(var.oidc_issuer_url, "https://", "") : ""
}

data "aws_iam_policy_document" "privilege_assume" {
  for_each = toset(local.privilege_classes)

  dynamic "statement" {
    for_each = local.irsa_enabled ? [1] : []
    content {
      actions = ["sts:AssumeRoleWithWebIdentity"]
      principals {
        type        = "Federated"
        identifiers = [var.oidc_provider_arn]
      }
      condition {
        test     = "StringEquals"
        variable = "${local.oidc_host}:aud"
        values   = ["sts.amazonaws.com"]
      }
      condition {
        test     = "StringEquals"
        variable = "${local.oidc_host}:sub"
        values = [
          "system:serviceaccount:${var.privilege_class_namespaces[each.key]}:${var.privilege_class_service_accounts[each.key]}"
        ]
      }
    }
  }

  dynamic "statement" {
    for_each = local.irsa_enabled ? [] : [1]
    content {
      actions = ["sts:AssumeRole"]
      principals {
        type        = "Service"
        identifiers = ["ec2.amazonaws.com"]
      }
    }
  }
}

resource "aws_iam_role" "privilege_class" {
  for_each = toset(local.privilege_classes)

  name               = "${var.name_prefix}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.privilege_assume[each.key].json
  tags = merge(var.tags, {
    PrivilegeClass = each.key
    IRSA           = local.irsa_enabled ? "enabled" : "pending-oidc"
    Namespace      = var.privilege_class_namespaces[each.key]
    ServiceAccount = var.privilege_class_service_accounts[each.key]
  })
}
