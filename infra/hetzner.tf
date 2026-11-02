locals {
  backup_service = templatefile("${path.module}/../ops/production/backup-schedule/rngwars-sqlite-backup.service", var.installation)
  cloud_init = templatefile("${path.module}/cloud-init.yml", {
    hostname               = var.server_name
    installation           = var.installation
    production_compose     = file("${path.module}/../ops/production/docker-compose.yml")
    backup_script          = file("${path.module}/../scripts/sqlite-backup.py")
    backup_policy          = file("${path.module}/../scripts/backup_policy.py")
    backup_schedule_script = file("${path.module}/../scripts/sqlite-backup-schedule.py")
    backup_service         = local.backup_service
    backup_timer           = file("${path.module}/../ops/production/backup-schedule/rngwars-sqlite-backup.timer")
  })
}

resource "hcloud_firewall" "game_server" {
  name = var.firewall_name

  dynamic "rule" {
    for_each = var.firewall_rules
    content {
      direction  = "in"
      protocol   = rule.value.protocol
      port       = rule.value.port
      source_ips = rule.value.source_ips
    }
  }
}

resource "hcloud_server" "game" {
  name         = var.server_name
  server_type  = var.server_type
  location     = var.location
  image        = var.image
  user_data    = local.cloud_init
  firewall_ids = [hcloud_firewall.game_server.id]
  labels       = var.server_labels

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [user_data]
  }
}
