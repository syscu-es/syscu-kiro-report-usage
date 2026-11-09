# Least-privilege, read-only access for kiro-report. Mirrors docs/PERMISSIONS.md
# with the real bucket ARNs substituted (no bucket wildcards).

locals {
  reader_bucket_names = compact([local.reader_cur_bucket, local.reader_activity_bucket])
  reader_bucket_arns = flatten([
    for name in local.reader_bucket_names : [
      "arn:${local.partition}:s3:::${name}",
      "arn:${local.partition}:s3:::${name}/*",
    ]
  ])
}

data "aws_iam_policy_document" "reader" {
  count = var.create_reader_policy ? 1 : 0

  statement {
    sid    = "Discover"
    effect = "Allow"
    actions = [
      "bcm-data-exports:ListExports",
      "bcm-data-exports:GetExport",
      "s3:ListAllMyBuckets",
      "sso:ListInstances",
    ]
    resources = ["*"]
  }

  dynamic "statement" {
    for_each = length(local.reader_bucket_arns) > 0 ? [1] : []

    content {
      sid       = "ReadReports"
      effect    = "Allow"
      actions   = ["s3:ListBucket", "s3:GetObject"]
      resources = local.reader_bucket_arns
    }
  }

  statement {
    sid       = "ResolveNames"
    effect    = "Allow"
    actions   = ["identitystore:DescribeUser"]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "reader" {
  count = var.create_reader_policy ? 1 : 0

  name        = "${var.name_prefix}-reader"
  description = "Read-only access for kiro-report (Kiro activity bucket, CUR bucket, name lookups)."
  policy      = data.aws_iam_policy_document.reader[0].json
}

data "aws_iam_policy_document" "reader_assume" {
  count = var.create_reader_role ? 1 : 0

  statement {
    sid     = "AssumeReader"
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.reader_principal_arns
    }
  }
}

resource "aws_iam_role" "reader" {
  count = var.create_reader_role ? 1 : 0

  name                 = "${var.name_prefix}-reader"
  description          = "Assumable role carrying the kiro-report read-only policy."
  assume_role_policy   = data.aws_iam_policy_document.reader_assume[0].json
  max_session_duration = var.reader_max_session_duration

  lifecycle {
    precondition {
      condition     = var.create_reader_policy
      error_message = "create_reader_role requires create_reader_policy = true."
    }

    precondition {
      condition     = length(var.reader_principal_arns) > 0
      error_message = "create_reader_role requires at least one entry in reader_principal_arns."
    }
  }
}

resource "aws_iam_role_policy_attachment" "reader" {
  count = var.create_reader_role ? 1 : 0

  role       = aws_iam_role.reader[0].name
  policy_arn = aws_iam_policy.reader[0].arn
}
