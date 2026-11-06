# AWS permissions

`kiro-report` is **read-only**. A minimal IAM policy for the identity that runs it:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "Discover", "Effect": "Allow",
      "Action": ["bcm-data-exports:ListExports", "bcm-data-exports:GetExport",
                 "s3:ListAllMyBuckets", "sso:ListInstances"],
      "Resource": "*" },
    { "Sid": "ReadReports", "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetObject"],
      "Resource": ["arn:aws:s3:::<cur-bucket>", "arn:aws:s3:::<cur-bucket>/*",
                   "arn:aws:s3:::<kiro-activity-bucket>", "arn:aws:s3:::<kiro-activity-bucket>/*"] },
    { "Sid": "ResolveNames", "Effect": "Allow",
      "Action": ["identitystore:DescribeUser"], "Resource": "*" }
  ]
}
```

`sts:GetCallerIdentity` needs no permission. If you pass `--cur-bucket/--cur-prefix`, `--activity-bucket` and `--identity-store-id`, the `Discover` statement is not needed.

### Using the AWS-managed `ReadOnlyAccess` role

Verified against a real IAM Identity Center permission set: `ReadOnlyAccess` does **not** include `bcm-data-exports:ListExports`. `kiro-report` handles it: when that call is denied it falls back to scanning the buckets whose name hints at billing data (`cur`, `cost`, `billing`, `report`) for `.../data/BILLING_PERIOD=YYYY-MM/*.parquet`, which only needs S3 read access. If your CUR bucket has an unrelated name, pass `--cur-bucket` and `--cur-prefix`.

Run it from the **payer / management account** that receives the Kiro charges, or from the account that owns the activity-report bucket (Kiro activity reports and CUR can live in different accounts: run once per account and combine with `--no-cur` / `--no-activity`).

## Enabling the Kiro user activity report

1. Create an S3 bucket (SSE-S3 or unencrypted; SSE-KMS needs `kms:Decrypt` for the reader).
2. Allow Kiro to write to it:

```json
{ "Sid": "KiroLogsWrite", "Effect": "Allow",
  "Principal": { "Service": "q.amazonaws.com" },
  "Action": "s3:PutObject",
  "Resource": "arn:aws:s3:::<bucket>/<prefix>/*",
  "Condition": {
    "StringEquals": { "aws:SourceAccount": "<account-id>" },
    "ArnLike": { "aws:SourceArn": "arn:aws:codewhisperer:<region>:<account-id>:*" } } }
```

3. Kiro console → *Settings* → *User activity report* → CSV → paste the bucket S3 URI.

Reports arrive daily (≈02:00 UTC) under `<prefix>/AWSLogs/<account>/KiroLogs/user_report/<region>/<yyyy>/<mm>/<dd>/<hh>/` as `KIRO_IDE_…`, `KIRO_CLI_…`, `KIRO_WEB_…` CSVs. An empty bucket after the first day usually means the console setting points to a different bucket or prefix than the policy.

## SSO profiles

For IAM Identity Center profiles (`sso_session` / `sso_start_url`), `kiro-report` runs `aws sso login --profile <name>` when the token is missing or expired (needs the AWS CLI v2 on `PATH`). The permission set used must include the actions above.
