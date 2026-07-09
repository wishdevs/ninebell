terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # 원격 상태를 쓰려면 아래 backend 를 채우세요(테스트는 로컬 상태로 시작해도 됩니다).
  # backend "s3" {
  #   bucket = "your-tfstate-bucket"
  #   key    = "ninebell-dashboard/test/terraform.tfstate"
  #   region = "ap-northeast-2"
  # }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = var.project
      Env     = var.env
      Managed = "terraform"
    }
  }
}
