output "activity_bucket_name" {
  description = "Name of the Kiro activity-report bucket (null when not created)."
  value       = var.create_activity_bucket ? aws_s3_bucket.activity[0].id : null
}

output "activity_report_s3_uri" {
  description = "MANUAL STEP: paste this URI in the Kiro console > Settings > User activity report. Terraform cannot enable the report itself."
  value       = var.create_activity_bucket ? "s3://${aws_s3_bucket.activity[0].id}${var.activity_prefix == "" ? "" : "/${var.activity_prefix}"}" : null
}

output "cur_bucket_name" {
  description = "Name of the CUR bucket (null when not created)."
  value       = var.create_cur_export ? aws_s3_bucket.cur[0].id : null
}

output "cur_prefix" {
  description = "Value for 'kiro-report --cur-prefix' (null when no CUR export was created). Data appears after the first export run, up to 24 hours after creation."
  value       = var.create_cur_export ? "${var.cur_prefix}/${var.cur_export_name}/data" : null
}

output "cur_export_arn" {
  description = "ARN of the CUR 2.0 export (null when not created)."
  value       = var.create_cur_export ? aws_bcmdataexports_export.cur[0].arn : null
}

output "reader_policy_arn" {
  description = "ARN of the read-only policy for kiro-report (null when not created)."
  value       = var.create_reader_policy ? aws_iam_policy.reader[0].arn : null
}

output "reader_role_arn" {
  description = "ARN of the assumable reader role (null when not created)."
  value       = var.create_reader_role ? aws_iam_role.reader[0].arn : null
}

output "kiro_report_command" {
  description = "Ready-to-run kiro-report command built from the resources above."
  value = join(" ", compact([
    "kiro-report",
    var.create_activity_bucket ? "--activity-bucket ${aws_s3_bucket.activity[0].id}" : "",
    var.create_activity_bucket && var.activity_prefix != "" ? "--activity-prefix ${var.activity_prefix}" : "",
    var.create_cur_export ? "--cur-bucket ${aws_s3_bucket.cur[0].id} --cur-prefix ${var.cur_prefix}/${var.cur_export_name}/data" : "",
  ]))
}
