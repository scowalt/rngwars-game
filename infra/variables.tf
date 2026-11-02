variable "server_name" {
  type        = string
  description = "Explicit reviewed identity of the physical resource, not an inferred application destination"
}

variable "server_type" {
  type        = string
  description = "Reviewed physical resource size; no rescale default"
}

variable "location" {
  type        = string
  description = "Reviewed physical resource location"
}

variable "image" {
  type        = string
  description = "Reviewed operating-system image identity"
}

variable "firewall_name" {
  type        = string
  description = "Existing physical firewall identity"
}

variable "firewall_rules" {
  type = list(object({
    protocol   = string
    port       = optional(string)
    source_ips = list(string)
  }))
  description = "Independently reviewed existing ingress rules; no default SSH or public access is supplied"
}

variable "server_labels" {
  type        = map(string)
  description = "Explicit physical resource ownership labels"
}

variable "cloudflare_zone_id" {
  description = "Private identifier of the approved DNS zone"
  type        = string
  sensitive   = true
}

variable "game_server_ip" {
  type        = string
  sensitive   = true
  description = "Reviewed application origin, independent of the physical server resource"
  validation {
    condition     = can(cidrhost("${var.game_server_ip}/32", 0)) && !strcontains(var.game_server_ip, ":")
    error_message = "Supply an explicit valid IPv4 application origin."
  }
}

variable "game_server_ipv6" {
  description = "Reviewed IPv6 application origin, independent of physical resource ownership"
  type        = string
  sensitive   = true
  validation {
    condition     = can(cidrhost("${var.game_server_ipv6}/128", 0)) && strcontains(var.game_server_ipv6, ":")
    error_message = "Supply an explicit valid IPv6 application origin."
  }
}

variable "game_record_name" {
  type        = string
  description = "Approved application record name within the configured zone"
}

variable "hsts_max_age" {
  description = "HSTS max-age in seconds"
  type        = number
  default     = 31536000
}

variable "hsts_include_subdomains" {
  description = "Whether the reviewed HSTS policy includes subdomains"
  type        = bool
  default     = true
}

variable "hsts_preload" {
  description = "Whether the reviewed HSTS policy permits preload"
  type        = bool
  default     = true
}

variable "min_tls_version" {
  description = "Minimum TLS version for the approved zone"
  type        = string
  default     = "1.2"
}

variable "repository_owner" {
  type        = string
  description = "Approved owner of the repository being managed"
}

variable "repository_name" {
  type        = string
  description = "Explicit repository identity; never infer a successor from an archive"
}

variable "repository_visibility" {
  description = "Explicit approved visibility for this managed repository"
  type        = string
  validation {
    condition     = contains(["private", "public"], var.repository_visibility)
    error_message = "Explicitly select the visibility of the managed repository."
  }
}

variable "repository_description" {
  description = "Public description of the managed repository"
  type        = string
  default     = "A satirical multiplayer game built with F# and SolidJS"
}

variable "default_branch" {
  description = "Default development branch protected by the API/frontend checks"
  type        = string
  default     = "main"
}

variable "installation" {
  type = object({
    helper_directory      = string
    data_directory        = string
    credentials_directory = string
    state_directory       = string
    compose_directory     = string
  })
  description = "Explicit private installation bindings; generated configuration must remain private"
  sensitive   = true
  validation {
    condition     = alltrue([for path in values(var.installation) : can(regex("^/[A-Za-z0-9_/-]+$", path)) && !strcontains(path, "..")]) && length(distinct(values(var.installation))) == 5
    error_message = "Use distinct absolute paths without traversal, interpolation, whitespace or shell syntax."
  }
}
