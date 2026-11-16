# Secrets Manager placeholders (O1). Values never land in git.

resource "random_password" "db_master" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "db_master" {
  name                    = "${var.name_prefix}/db/master"
  description             = "IncidentPilot Postgres master credentials"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-db-master"
  })
}

resource "aws_secretsmanager_secret_version" "db_master" {
  secret_id = aws_secretsmanager_secret.db_master.id
  secret_string = jsonencode({
    username = var.db_username
    password = random_password.db_master.result
    engine   = "postgres"
  })
}

resource "aws_secretsmanager_secret" "slack_bot" {
  name                    = "${var.name_prefix}/integrations/slack-bot"
  description             = "Slack bot token placeholder (fill after apply)"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-slack-bot"
  })
}

resource "aws_secretsmanager_secret_version" "slack_bot" {
  secret_id = aws_secretsmanager_secret.slack_bot.id
  secret_string = jsonencode({
    token = "REPLACE_ME"
  })
}

resource "aws_secretsmanager_secret" "oidc" {
  name                    = "${var.name_prefix}/auth/oidc"
  description             = "OIDC client credentials placeholder"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-oidc"
  })
}

resource "aws_secretsmanager_secret_version" "oidc" {
  secret_id = aws_secretsmanager_secret.oidc.id
  secret_string = jsonencode({
    client_id     = "REPLACE_ME"
    client_secret = "REPLACE_ME"
  })
}

# O6: Temporal Cloud API key (preferred for staging / production-demo).
resource "aws_secretsmanager_secret" "temporal_cloud" {
  name                    = "${var.name_prefix}/temporal/cloud"
  description             = "Temporal Cloud connection (address, namespace, api_key)"
  recovery_window_in_days = 0

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-temporal-cloud"
  })
}

resource "aws_secretsmanager_secret_version" "temporal_cloud" {
  secret_id = aws_secretsmanager_secret.temporal_cloud.id
  secret_string = jsonencode({
    address   = "REPLACE_ME.tmprl.cloud:7233"
    namespace = "REPLACE_ME"
    api_key   = "REPLACE_ME"
  })
}
