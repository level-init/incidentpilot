output "db_instance_id" {
  description = "RDS instance id."
  value       = aws_db_instance.this.id
}

output "db_endpoint" {
  description = "RDS endpoint hostname."
  value       = aws_db_instance.this.address
}

output "db_port" {
  description = "RDS port."
  value       = aws_db_instance.this.port
}

output "db_name" {
  description = "Database name."
  value       = aws_db_instance.this.db_name
}

output "security_group_id" {
  description = "RDS security group id."
  value       = aws_security_group.db.id
}
