resource "github_repository" "rngwars" {
  name        = var.repository_name
  description = var.repository_description
  visibility  = var.repository_visibility

  has_issues             = true
  has_discussions        = false
  has_projects           = false
  has_wiki               = false
  vulnerability_alerts   = true
  delete_branch_on_merge = true
  allow_squash_merge     = true
  allow_merge_commit     = true
  allow_rebase_merge     = true
  allow_auto_merge       = true

  topics = [
    "game",
    "fsharp",
    "dotnet",
    "giraffe",
    "signalr",
    "solidjs",
    "sqlite",
  ]
}

resource "github_branch_protection" "main" {
  repository_id = github_repository.rngwars.node_id
  pattern       = var.default_branch

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    required_approving_review_count = 0
  }

  required_status_checks {
    strict = true
    contexts = [
      "Build API (F#)",
      "Build Frontend (SolidJS)",
      "Portable SQLite backup and deployment preparation",
    ]
  }

  enforce_admins = true

  allows_force_pushes = false

  allows_deletions = false

  require_conversation_resolution = true

  lock_branch = false
}

resource "github_branch_protection" "release" {
  repository_id = github_repository.rngwars.node_id
  pattern       = "release"

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    required_approving_review_count = 0
  }

  required_status_checks {
    strict = true
    contexts = [
      "Build API (F#)",
      "Build Frontend (SolidJS)",
    ]
  }

  enforce_admins      = false
  allows_force_pushes = false
  allows_deletions    = false
}

resource "github_branch_protection" "production" {
  repository_id = github_repository.rngwars.node_id
  pattern       = "production"

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    required_approving_review_count = 1
  }

  required_status_checks {
    strict = true
    contexts = [
      "Build API (F#)",
      "Build Frontend (SolidJS)",
    ]
  }

  enforce_admins      = false
  allows_force_pushes = false
  allows_deletions    = false

  require_conversation_resolution = true
}


locals {
  labels = {
    "bug" = {
      color       = "d73a4a"
      description = "Something isn't working"
    }
    "enhancement" = {
      color       = "a2eeef"
      description = "New feature or request"
    }
    "documentation" = {
      color       = "0075ca"
      description = "Improvements or additions to documentation"
    }
    "security" = {
      color       = "ee0000"
      description = "Security vulnerability or concern"
    }
    "infrastructure" = {
      color       = "7057ff"
      description = "Infrastructure, CI/CD, or deployment"
    }
    "game" = {
      color       = "008672"
      description = "Game server (F# Giraffe)"
    }
    "frontend" = {
      color       = "ffd700"
      description = "SolidJS frontend"
    }
    "dependencies" = {
      color       = "0366d6"
      description = "Pull requests that update a dependency file"
    }
  }
}

resource "github_issue_label" "labels" {
  for_each = local.labels

  repository  = github_repository.rngwars.name
  name        = each.key
  color       = each.value.color
  description = each.value.description
}

