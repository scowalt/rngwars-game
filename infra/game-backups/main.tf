terraform {
  required_version = ">= 1.9.0"
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5"
    }
  }
}

provider "cloudflare" {}

locals {
  bucket_name = var.bucket_name
  prefix      = var.repository_prefix
  repository  = "s3:https://${var.account_id}.r2.cloudflarestorage.com/${local.bucket_name}/${local.prefix}"
  credential_request = {
    name = var.credential_request_name
    policies = [{
      effect = "allow"
      resources = {
        "com.cloudflare.edge.r2.bucket.${var.account_id}_default_${local.bucket_name}" = "*"
      }
      permission_groups = [{
        id   = var.bucket_item_write_permission_group_id
        name = "Workers R2 Storage Bucket Item Write"
      }]
    }]
  }
}

resource "cloudflare_r2_bucket" "game_backups" {
  account_id = var.account_id
  name       = local.bucket_name
  location   = var.bucket_location
  lifecycle {
    prevent_destroy = true
  }
}
