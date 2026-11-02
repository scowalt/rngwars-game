locals {
  application_origins = {
    ipv4        = var.game_server_ip
    ipv6        = var.game_server_ipv6
    record_name = var.game_record_name
  }
}
