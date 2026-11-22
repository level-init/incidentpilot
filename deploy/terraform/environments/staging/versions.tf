terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
    tls = {
      source  = "hashicorp/tls"
      version = ">= 4.0"
    }
  }

  # O8: for ephemeral/shared staging applies, uncomment and init with backend.hcl:
  #   cp backend.hcl.example backend.hcl   # fill bucket/key (do not commit)
  #   terraform init -backend-config=backend.hcl
  # Leave commented for `make terraform-validate` (init -backend=false).
  # backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
