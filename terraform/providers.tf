# Default provider: the region where the S3 buckets and IAM objects live.
provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

# The Billing and Cost Management Data Exports API is only served from
# us-east-1, whatever region the rest of the stack uses. Only the CUR export
# resource uses this alias; buckets and policies stay in var.region.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.tags
  }
}
