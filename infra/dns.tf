
resource "cloudflare_zone_setting" "always_use_https" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "always_use_https"
  value      = "on"
}

resource "cloudflare_zone_setting" "min_tls_version" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "min_tls_version"
  value      = var.min_tls_version
}

resource "cloudflare_zone_setting" "ssl" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "ssl"
  value      = "strict"
}

resource "cloudflare_zone_setting" "tls_1_3" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "tls_1_3"
  value      = "on"
}

resource "cloudflare_zone_setting" "security_header" {
  zone_id    = var.cloudflare_zone_id
  setting_id = "security_header"
  value = {
    strict_transport_security = {
      enabled            = true
      include_subdomains = var.hsts_include_subdomains
      max_age            = var.hsts_max_age
      nosniff            = true
      preload            = var.hsts_preload
    }
  }
}

resource "cloudflare_dns_record" "game_play" {
  count = 1

  zone_id = var.cloudflare_zone_id
  name    = var.game_record_name
  type    = "A"
  content = var.game_server_ip
  proxied = true
  ttl     = 1

  comment = "Application origin; independent of physical resource ownership"
}

resource "cloudflare_dns_record" "game_play_ipv6" {
  count = 1

  zone_id = var.cloudflare_zone_id
  name    = var.game_record_name
  type    = "AAAA"
  content = var.game_server_ipv6
  proxied = true
  ttl     = 1

  comment = "Application IPv6 origin; independent of physical resource ownership"
}
