output "bucket_ids" {
  description = "Map of role → bucket id."
  value       = { for k, b in aws_s3_bucket.this : k => b.id }
}

output "bucket_arns" {
  description = "Map of role → bucket ARN."
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}

output "evidence_bucket_id" {
  description = "Evidence blob bucket id."
  value       = aws_s3_bucket.this["evidence"].id
}

output "exports_bucket_id" {
  description = "Exports bucket id."
  value       = aws_s3_bucket.this["exports"].id
}
