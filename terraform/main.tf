data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  account_id = coalesce(var.account_id, data.aws_caller_identity.current.account_id)
  partition  = data.aws_partition.current.partition

  tags = merge(
    {
      Project   = "kiro-usage-report"
      ManagedBy = "terraform"
    },
    var.tags,
  )

  activity_bucket_name = coalesce(var.activity_bucket_name, "kiro-activity-${local.account_id}-${var.region}")
  cur_bucket_name      = coalesce(var.cur_bucket_name, "kiro-cur-${local.account_id}-${var.region}")

  # Prefix helpers: "" stays "", otherwise "<prefix>/".
  activity_prefix_path = var.activity_prefix == "" ? "" : "${var.activity_prefix}/"

  # Buckets the reader policy may reference: the ones we create, or the ones the
  # caller named explicitly. A bucket nobody named is simply left out.
  reader_activity_bucket = var.create_activity_bucket || var.activity_bucket_name != null ? local.activity_bucket_name : null
  reader_cur_bucket      = var.create_cur_export || var.cur_bucket_name != null ? local.cur_bucket_name : null
}
