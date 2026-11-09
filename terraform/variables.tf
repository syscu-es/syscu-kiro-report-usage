variable "region" {
  description = "Region for the S3 buckets and IAM objects. Should match the region of your Kiro profile / IAM Identity Center unless you have a reason not to."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]$", var.region))
    error_message = "region must look like an AWS region name, e.g. us-east-1 or eu-west-1."
  }
}

variable "account_id" {
  description = "12-digit AWS account ID that owns the Kiro subscription. Leave null to use the account of the active credentials."
  type        = string
  default     = null

  validation {
    condition     = var.account_id == null || can(regex("^[0-9]{12}$", coalesce(var.account_id, "x")))
    error_message = "account_id must be exactly 12 digits (e.g. 123456789012) or null."
  }
}

variable "name_prefix" {
  description = "Prefix for the names of IAM and CUR objects created by this module."
  type        = string
  default     = "kiro-report"

  validation {
    condition     = can(regex("^[A-Za-z0-9+=,.@_-]{1,32}$", var.name_prefix))
    error_message = "name_prefix must be 1-32 characters from [A-Za-z0-9+=,.@_-] (IAM-safe)."
  }
}

variable "tags" {
  description = "Extra tags merged over the default tags (Project, ManagedBy) and applied to every taggable resource."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# Kiro activity-report bucket
# ---------------------------------------------------------------------------

variable "create_activity_bucket" {
  description = "Create the S3 bucket (and bucket policy) that receives the Kiro user activity report."
  type        = bool
  default     = true
}

variable "activity_bucket_name" {
  description = "Globally unique name of the activity-report bucket. Leave null to derive 'kiro-activity-<account>-<region>'. When create_activity_bucket is false, set it to an existing bucket so the reader policy can reference it."
  type        = string
  default     = null

  validation {
    condition = var.activity_bucket_name == null || (
      can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", coalesce(var.activity_bucket_name, "x"))) &&
      !can(regex("\\.\\.|^xn--|-s3alias$|--ol-s3$|^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$", coalesce(var.activity_bucket_name, "x")))
    )
    error_message = "activity_bucket_name must be a valid S3 bucket name: 3-63 chars, lowercase letters, digits, dots and hyphens, starting and ending with a letter or digit, no '..', not an IP address, no reserved prefix/suffix."
  }
}

variable "activity_prefix" {
  description = "Key prefix Kiro writes under (no leading or trailing slash). Must match the prefix of the S3 URI pasted in the Kiro console. Empty string means the bucket root."
  type        = string
  default     = "kiro"

  validation {
    condition     = var.activity_prefix == "" || can(regex("^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$", var.activity_prefix))
    error_message = "activity_prefix must be empty or slash-separated segments of [A-Za-z0-9._-] with no leading or trailing slash."
  }
}

variable "kiro_source_region" {
  description = "Region of your Kiro profile / IAM Identity Center instance. Used in the aws:SourceArn condition (arn:aws:codewhisperer:<region>:<account>:*)."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]$", var.kiro_source_region))
    error_message = "kiro_source_region must look like an AWS region name, e.g. us-east-1."
  }
}

variable "activity_versioning" {
  description = "Enable S3 versioning on the activity bucket. Not needed for a re-creatable report; versions are expired after 30 days when enabled."
  type        = bool
  default     = false
}

variable "activity_expiration_days" {
  description = "Delete activity reports after this many days. Set to 0 to keep them forever."
  type        = number
  default     = 400

  validation {
    condition     = var.activity_expiration_days >= 0 && var.activity_expiration_days == floor(var.activity_expiration_days)
    error_message = "activity_expiration_days must be a whole number >= 0."
  }
}

variable "force_destroy" {
  description = "Allow 'terraform destroy' to delete the buckets even when they contain objects. Keep false unless you really want the data gone."
  type        = bool
  default     = false
}

# ---------------------------------------------------------------------------
# CUR 2.0 export
# ---------------------------------------------------------------------------

variable "create_cur_export" {
  description = "Create a CUR 2.0 Data Export (parquet, with resource IDs) and its bucket. Must be applied from the payer / management account. The Data Exports API is us-east-1 only (handled by an aliased provider)."
  type        = bool
  default     = false
}

variable "cur_bucket_name" {
  description = "Globally unique name of the CUR bucket. Leave null to derive 'kiro-cur-<account>-<region>'. When create_cur_export is false, set it to an existing CUR bucket so the reader policy can reference it."
  type        = string
  default     = null

  validation {
    condition = var.cur_bucket_name == null || (
      can(regex("^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", coalesce(var.cur_bucket_name, "x"))) &&
      !can(regex("\\.\\.|^xn--|-s3alias$|--ol-s3$|^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$", coalesce(var.cur_bucket_name, "x")))
    )
    error_message = "cur_bucket_name must be a valid S3 bucket name: 3-63 chars, lowercase letters, digits, dots and hyphens, starting and ending with a letter or digit, no '..', not an IP address, no reserved prefix/suffix."
  }
}

variable "cur_prefix" {
  description = "Key prefix of the export inside the CUR bucket (no leading or trailing slash). Data lands under <cur_prefix>/<cur_export_name>/data/."
  type        = string
  default     = "cur"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$", var.cur_prefix))
    error_message = "cur_prefix must be slash-separated segments of [A-Za-z0-9._-] with no leading or trailing slash."
  }
}

variable "cur_export_name" {
  description = "Name of the CUR 2.0 export."
  type        = string
  default     = "kiro-cur"

  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,128}$", var.cur_export_name))
    error_message = "cur_export_name must be 1-128 characters from [A-Za-z0-9_-]."
  }
}

variable "cur_refresh_frequency" {
  description = "How often AWS refreshes the export. The Data Exports API currently only accepts SYNCHRONOUS (updated up to 3 times a day, overwriting the month's files)."
  type        = string
  default     = "SYNCHRONOUS"

  validation {
    condition     = contains(["SYNCHRONOUS"], var.cur_refresh_frequency)
    error_message = "cur_refresh_frequency must be SYNCHRONOUS."
  }
}

variable "cur_expiration_days" {
  description = "Delete CUR objects after this many days. Set to 0 to keep them forever (CUR parquet is small; this is mostly a hygiene knob)."
  type        = number
  default     = 0

  validation {
    condition     = var.cur_expiration_days >= 0 && var.cur_expiration_days == floor(var.cur_expiration_days)
    error_message = "cur_expiration_days must be a whole number >= 0."
  }
}

# ---------------------------------------------------------------------------
# Read-only access for kiro-report
# ---------------------------------------------------------------------------

variable "create_reader_policy" {
  description = "Create a customer-managed, read-only IAM policy with exactly what kiro-report needs (see docs/PERMISSIONS.md)."
  type        = bool
  default     = true
}

variable "create_reader_role" {
  description = "Also create an IAM role that carries the reader policy and can be assumed by reader_principal_arns. Requires create_reader_policy and a non-empty reader_principal_arns. No IAM users or access keys are ever created."
  type        = bool
  default     = false
}

variable "reader_principal_arns" {
  description = "IAM principal ARNs (users, roles, root of a trusted account) allowed to assume the reader role."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for arn in var.reader_principal_arns : can(regex("^arn:aws[a-z-]*:iam::[0-9]{12}:(root|user/.+|role/.+)$", arn))])
    error_message = "Each reader principal must be an IAM ARN: arn:aws:iam::<12-digit-account>:(root|user/...|role/...)."
  }
}

variable "reader_max_session_duration" {
  description = "Maximum session duration in seconds for the reader role (3600-43200)."
  type        = number
  default     = 3600

  validation {
    condition     = var.reader_max_session_duration >= 3600 && var.reader_max_session_duration <= 43200
    error_message = "reader_max_session_duration must be between 3600 and 43200 seconds."
  }
}
