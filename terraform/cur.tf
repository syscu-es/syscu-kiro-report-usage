# CUR 2.0 Data Export (parquet, with resource IDs) delivered to its own bucket.
#
# Apply from the payer / management account. The BCM Data Exports API is only
# available in us-east-1, hence the aliased provider on the export resource.
# The bucket itself lives in var.region.

resource "aws_s3_bucket" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket        = local.cur_bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket                  = aws_s3_bucket.cur[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket = aws_s3_bucket.cur[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket = aws_s3_bucket.cur[0].id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket = aws_s3_bucket.cur[0].id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = var.cur_expiration_days > 0 ? [1] : []

    content {
      id     = "expire-cur"
      status = "Enabled"

      filter {}

      expiration {
        days = var.cur_expiration_days
      }
    }
  }
}

# Policy documented by AWS for Data Exports / legacy CUR delivery, scoped to
# this account and to exports in it.
data "aws_iam_policy_document" "cur_bucket" {
  count = var.create_cur_export ? 1 : 0

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.cur[0].arn,
      "${aws_s3_bucket.cur[0].arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "EnableAWSDataExportsToWriteToS3AndCheckPolicy"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetBucketPolicy"]
    resources = [aws_s3_bucket.cur[0].arn, "${aws_s3_bucket.cur[0].arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["billingreports.amazonaws.com", "bcm-data-exports.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "StringLike"
      variable = "aws:SourceArn"
      values = [
        "arn:${local.partition}:cur:us-east-1:${local.account_id}:definition/*",
        "arn:${local.partition}:bcm-data-exports:us-east-1:${local.account_id}:export/*",
      ]
    }
  }
}

resource "aws_s3_bucket_policy" "cur" {
  count = var.create_cur_export ? 1 : 0

  bucket = aws_s3_bucket.cur[0].id
  policy = data.aws_iam_policy_document.cur_bucket[0].json

  depends_on = [aws_s3_bucket_public_access_block.cur]
}

resource "aws_bcmdataexports_export" "cur" {
  count    = var.create_cur_export ? 1 : 0
  provider = aws.us_east_1

  export {
    name        = var.cur_export_name
    description = "CUR 2.0 (parquet, resource IDs) for kiro-report"

    data_query {
      # Only the columns kiro-report reads, plus context columns that make the
      # file useful elsewhere. INCLUDE_RESOURCES is what exposes
      # line_item_resource_id (the per-user Kiro subscription ARN).
      query_statement = <<-SQL
        SELECT
          bill_billing_period_start_date,
          bill_payer_account_id,
          line_item_usage_account_id,
          line_item_line_item_type,
          line_item_product_code,
          line_item_usage_type,
          line_item_operation,
          line_item_resource_id,
          line_item_usage_start_date,
          line_item_usage_end_date,
          line_item_usage_amount,
          line_item_unblended_cost,
          line_item_currency_code
        FROM COST_AND_USAGE_REPORT
      SQL

      table_configurations = {
        COST_AND_USAGE_REPORT = {
          TIME_GRANULARITY                      = "DAILY"
          INCLUDE_RESOURCES                     = "TRUE"
          INCLUDE_MANUAL_DISCOUNT_COMPATIBILITY = "FALSE"
          INCLUDE_SPLIT_COST_ALLOCATION_DATA    = "FALSE"
          # required by the provider when table_configurations is set for the Cost and Usage Report
          BILLING_VIEW_ARN = "arn:${local.partition}:billing::${local.account_id}:billingview/primary"
        }
      }
    }

    destination_configurations {
      s3_destination {
        s3_bucket = aws_s3_bucket.cur[0].id
        s3_prefix = var.cur_prefix
        s3_region = aws_s3_bucket.cur[0].region

        s3_output_configurations {
          compression = "PARQUET"
          format      = "PARQUET"
          output_type = "CUSTOM"
          overwrite   = "OVERWRITE_REPORT"
        }
      }
    }

    refresh_cadence {
      frequency = var.cur_refresh_frequency
    }
  }

  depends_on = [aws_s3_bucket_policy.cur]
}
