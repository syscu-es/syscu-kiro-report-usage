# S3 bucket that receives the Kiro "User activity report".
#
# Terraform cannot turn the report on: that is a manual step in the Kiro
# console (Settings > User activity report). See the activity_report_s3_uri
# output.

resource "aws_s3_bucket" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket        = local.activity_bucket_name
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_public_access_block" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket                  = aws_s3_bucket.activity[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket = aws_s3_bucket.activity[0].id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 on purpose: the reader then needs no kms:Decrypt (docs/PERMISSIONS.md).
resource "aws_s3_bucket_server_side_encryption_configuration" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket = aws_s3_bucket.activity[0].id

  rule {
    bucket_key_enabled = true

    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket = aws_s3_bucket.activity[0].id

  versioning_configuration {
    status = var.activity_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket = aws_s3_bucket.activity[0].id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = var.activity_expiration_days > 0 ? [1] : []

    content {
      id     = "expire-reports"
      status = "Enabled"

      filter {}

      expiration {
        days = var.activity_expiration_days
      }

      dynamic "noncurrent_version_expiration" {
        for_each = var.activity_versioning ? [1] : []

        content {
          noncurrent_days = 30
        }
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.activity]
}

data "aws_iam_policy_document" "activity_bucket" {
  count = var.create_activity_bucket ? 1 : 0

  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]
    resources = [
      aws_s3_bucket.activity[0].arn,
      "${aws_s3_bucket.activity[0].arn}/*",
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

  # Same statement as docs/PERMISSIONS.md, with the confused-deputy conditions.
  statement {
    sid       = "KiroLogsWrite"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.activity[0].arn}/${local.activity_prefix_path}*"]

    principals {
      type        = "Service"
      identifiers = ["q.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.partition}:codewhisperer:${var.kiro_source_region}:${local.account_id}:*"]
    }
  }
}

resource "aws_s3_bucket_policy" "activity" {
  count = var.create_activity_bucket ? 1 : 0

  bucket = aws_s3_bucket.activity[0].id
  policy = data.aws_iam_policy_document.activity_bucket[0].json

  depends_on = [aws_s3_bucket_public_access_block.activity]
}
