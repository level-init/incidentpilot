output "db_master_secret_arn" {
  description = "ARN of the DB master secret."
  value       = aws_secretsmanager_secret.db_master.arn
}

output "db_master_password" {
  description = "Generated DB master password (pass to RDS module; sensitive)."
  value       = random_password.db_master.result
  sensitive   = true
}

output "slack_bot_secret_arn" {
  description = "ARN of the Slack bot secret placeholder."
  value       = aws_secretsmanager_secret.slack_bot.arn
}

output "oidc_secret_arn" {
  description = "ARN of the OIDC secret placeholder."
  value       = aws_secretsmanager_secret.oidc.arn
}

output "secret_arns" {
  description = "Map of logical name → secret ARN."
  value = {
    db_master = aws_secretsmanager_secret.db_master.arn
    slack_bot = aws_secretsmanager_secret.slack_bot.arn
    oidc      = aws_secretsmanager_secret.oidc.arn
  }
}
