
output "server_ipv4" {
  description = "Physical resource IPv4, not an inferred application destination"
  sensitive   = true
  value       = hcloud_server.game.ipv4_address
}

output "server_ipv6" {
  description = "Physical resource IPv6, not an inferred application destination"
  sensitive   = true
  value       = hcloud_server.game.ipv6_address
}

output "server_id" {
  description = "Physical resource ID"
  sensitive   = true
  value       = hcloud_server.game.id
}

output "server_status" {
  description = "Physical resource status"
  sensitive   = true
  value       = hcloud_server.game.status
}


output "zone_id" {
  description = "The zone ID for the domain"
  sensitive   = true
  value       = var.cloudflare_zone_id
}

output "hsts_configuration" {
  description = "HSTS configuration applied"
  value = {
    max_age            = var.hsts_max_age
    include_subdomains = var.hsts_include_subdomains
    preload            = var.hsts_preload
  }
}

output "security_settings" {
  description = "Applied security settings"
  value = {
    always_use_https = "on"
    min_tls_version  = var.min_tls_version
    ssl              = "strict"
    tls_1_3          = "on"
  }
}


output "repository_url" {
  description = "GitHub repository URL"
  value       = github_repository.rngwars.html_url
}

output "repository_clone_url" {
  description = "Git clone URL"
  value       = github_repository.rngwars.ssh_clone_url
}

output "branch_protection_rules" {
  description = "Active branch protection rules"
  value = {
    main    = github_branch_protection.main.pattern
    release = github_branch_protection.release.pattern
  }
}

output "required_status_checks" {
  description = "Required CI checks for main branch"
  value       = github_branch_protection.main.required_status_checks[0].contexts
}

output "application_origins" {
  description = "Explicit application destinations, never inferred from the physical server outputs"
  sensitive   = true
  value       = local.application_origins
}
