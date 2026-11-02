output "repository" {
  description = "Private address of the approved backup repository"
  sensitive   = true
  value       = local.repository
}

output "scoped_credential_provisioning_request" {
  description = "Request template only; this module does not mint a credential"
  sensitive   = true
  value       = local.credential_request
}

output "independent_recovery_secret_names" {
  description = "Names only of the original recovery values required independently of a host"
  value       = ["RNGWARS_BACKUP_RESTIC_PASSWORD", "RNGWARS_BACKUP_AWS_ACCESS_KEY_ID", "RNGWARS_BACKUP_AWS_SECRET_ACCESS_KEY", "RNGWARS_BACKUP_REPOSITORY"]
}
