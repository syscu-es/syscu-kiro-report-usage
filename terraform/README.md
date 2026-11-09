# Optional Terraform module

Provisions the AWS pieces `kiro-report` reads. **Nothing here is required**: if you already have a Kiro activity bucket, a CUR export and a suitably scoped identity, skip this directory. See [docs/PERMISSIONS.md](../docs/PERMISSIONS.md) for what the tool needs and why.

What it can create, each behind a boolean:

| Variable | Default | Creates |
|---|---|---|
| `create_activity_bucket` | `true` | S3 bucket for the Kiro user activity report: public access blocked, SSE-S3, TLS-only policy, lifecycle expiry (default 400 days), optional versioning, plus the `q.amazonaws.com` `s3:PutObject` statement (scoped with `aws:SourceAccount` and `aws:SourceArn`). |
| `create_cur_export` | `false` | CUR 2.0 Data Export (`aws_bcmdataexports_export`: parquet, resource IDs, daily granularity, `OVERWRITE_REPORT`) and its bucket with the policy billing exports require. |
| `create_reader_policy` | `true` | Customer-managed read-only IAM policy equal to docs/PERMISSIONS.md, with the real bucket ARNs substituted. |
| `create_reader_role` | `false` | IAM role carrying that policy, assumable by `reader_principal_arns`. |

It deliberately creates **no Glue, no Athena, and no IAM users or access keys**: `kiro-report` reads S3 directly with whatever credentials you already use.

## Usage

Requires Terraform >= 1.5 and AWS credentials for the account that owns the Kiro subscription.

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # edit; this file is git-ignored
terraform init
terraform plan
terraform apply
```

### Manual step Terraform cannot do

Terraform cannot enable the report. After `apply`, open the Kiro console, go to **Settings > User activity report**, choose CSV and paste the `activity_report_s3_uri` output (for example `s3://kiro-activity-123456789012-us-east-1/kiro`). If the console prefix differs from `activity_prefix`, the bucket policy will not match and the bucket stays empty. The first reports arrive about a day later.

### CUR export notes

- Apply from the **payer / management account**.
- The Billing and Cost Management Data Exports API only exists in **us-east-1**. The module uses an aliased provider (`aws.us_east_1`) for the export resource, so you may set `region` to anything; the CUR bucket is created in `region`.
- The first delivery can take up to 24 hours. Files land under `<cur_prefix>/<export name>/data/BILLING_PERIOD=YYYY-MM/`, which is what `--cur-prefix` expects (the `cur_prefix` output already includes `/data`).
- `INCLUDE_RESOURCES` must stay on: `kiro-report` attributes cost per user through `line_item_resource_id`.

### Feeding the outputs to kiro-report

```bash
terraform output kiro_report_command     # prints a ready-to-run command, or build it yourself:

kiro-report \
  --activity-bucket "$(terraform output -raw activity_bucket_name)" \
  --activity-prefix kiro \
  --cur-bucket "$(terraform output -raw cur_bucket_name)" \
  --cur-prefix "$(terraform output -raw cur_prefix)"
```

If you created `create_reader_role`, configure an AWS CLI profile with `role_arn = <reader_role_arn output>` and run `kiro-report --profile <name>`. Attach `reader_policy_arn` to an existing role or permission set otherwise (IAM Identity Center needs a customer-managed policy attachment by name).

### Reusing existing buckets

Set `create_activity_bucket = false` and/or `create_cur_export = false` and give `activity_bucket_name` / `cur_bucket_name` so the reader policy still lists the right buckets (no wildcards are ever used).

## Cost

Negligible: a few MB of CSV per month in S3 (cents at most), CUR parquet is similarly small, and bucket policies, IAM objects and the export itself are free. Data Exports has no charge; standard S3 request and storage rates apply.

## Security decisions

- All buckets: all four public-access blocks, `BucketOwnerEnforced`, SSE-S3 (so the reader needs no KMS permission), deny non-TLS requests.
- The Kiro statement is limited to `PutObject` under the configured prefix and conditioned on your account and the CodeWhisperer ARN of your Kiro region (`kiro_source_region`), preventing confused-deputy writes from other accounts.
- The reader policy is read-only; the `Resource: "*"` statements are the same list/describe calls docs/PERMISSIONS.md documents, which do not support resource-level scoping for `s3:ListAllMyBuckets`, `sso:ListInstances` and Data Exports discovery.
- The reader role trust policy accepts only explicit IAM principal ARNs (validated); no wildcards. Passing `arn:aws:iam::<account>:root` trusts every principal of that account that is allowed `sts:AssumeRole`: prefer specific role ARNs, because the activity report exposes user e-mails.
- Encryption is SSE-S3 on purpose (the reader needs no `kms:Decrypt`). Server access logging is not enabled; add it if your compliance regime requires it.
- Set `account_id` only if it equals the credentials' account: it feeds `aws:SourceAccount`, and a mismatch makes deliveries fail silently.

## Verification status

Validated with `terraform validate`/`fmt` and checked against the AWS and provider documentation (bucket-policy principals and `aws:SourceArn` patterns for Data Exports, `SYNCHRONOUS` refresh, parquet output, `BILLING_VIEW_ARN`). `terraform plan` was run read-only against a real account with every toggle on (15 resources to add, none to change or destroy), and the planned export settings (`table_configurations` incl. `BILLING_VIEW_ARN`, `INCLUDE_RESOURCES = "TRUE"`, `DAILY`, `PARQUET`/`CUSTOM`/`OVERWRITE_REPORT`, `SYNCHRONOUS`) match those of a working Data Export already running in that account. **`terraform apply` has not been exercised yet**, so the first apply of `create_cur_export = true` is still the real end-to-end test: try it in a sandbox account first. The Kiro `aws:SourceArn` is taken from [docs/PERMISSIONS.md](../docs/PERMISSIONS.md).
- `force_destroy` defaults to `false`.
- Activity data contains user identifiers (IAM Identity Center user IDs): keep the bucket private and prune with `activity_expiration_days`.

## Destroying

```bash
terraform destroy
```

Buckets that still contain objects are not deleted unless you first set `force_destroy = true` and apply (or empty them yourself). Destroying the activity bucket stops Kiro delivery: clear the setting in the Kiro console first. State is local by default; add a backend block of your own if several people manage this.

## Files

`versions.tf`, `providers.tf`, `variables.tf` (inputs and validation), `main.tf` (locals), `activity.tf`, `cur.tf`, `iam.tf`, `outputs.tf`, `terraform.tfvars.example`, `.terraform.lock.hcl` (provider checksums, committed).
