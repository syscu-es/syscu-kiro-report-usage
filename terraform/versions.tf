terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # aws_bcmdataexports_export is documented from v5.47.0; 5.60 is a conservative floor.
      version = ">= 5.60.0, < 7.0.0"
    }
  }
}
