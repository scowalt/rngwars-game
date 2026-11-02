variable "account_id" {
  type        = string
  description = "Approved account for the dedicated game backup bucket"
  validation {
    condition     = can(regex("^[a-f0-9]{32}$", var.account_id))
    error_message = "Use an explicit Cloudflare account identifier."
  }
}

variable "bucket_item_write_permission_group_id" {
  type        = string
  description = "Operator-verified bucket-item permission group for the separately approved credential request"
  validation {
    condition     = can(regex("^[a-f0-9]{32}$", var.bucket_item_write_permission_group_id))
    error_message = "Supply the verified bucket item write permission group identifier."
  }
}

variable "bucket_name" {
  type        = string
  description = "Reviewed dedicated backup bucket identity; never a state or CI artifact bucket"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", var.bucket_name))
    error_message = "Supply an explicit valid bucket identity."
  }
}

variable "repository_prefix" {
  type        = string
  description = "Original approved backup repository prefix; do not change to initialize another repository"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*$", var.repository_prefix))
    error_message = "Supply an explicit backup prefix without traversal."
  }
}

variable "bucket_location" {
  type        = string
  description = "Reviewed existing location; never infer a migration from a default"
}

variable "credential_request_name" {
  type        = string
  description = "Label for a separately approved bucket-scoped credential request"
}
