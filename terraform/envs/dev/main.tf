# Dev environment — composes all modules

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # For real usage, add an S3 backend:
  # backend "s3" { ... }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  type    = string
  default = "us-west-2"
}

variable "project_name" {
  type    = string
  default = "ragops"
}

variable "environment" {
  type    = string
  default = "dev"
}

# --- Secrets passed via TF_VAR_... ---
variable "neon_connection_string" {
  description = "Neon DB connection string"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  type      = string
  sensitive = true
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "groq_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "llm_provider" {
  type    = string
  default = "openai"
}

variable "llm_enabled" {
  type    = bool
  default = false
}

variable "embedding_provider" {
  type    = string
  default = "openai"
}


# ----------------------------------------------------------------
# Modules
# ----------------------------------------------------------------
module "s3" {
  source       = "../../modules/s3"
  project_name = var.project_name
  environment  = var.environment
}

module "iam" {
  source        = "../../modules/iam"
  project_name  = var.project_name
  environment   = var.environment
  s3_bucket_arn = module.s3.bucket_arn
  # Removed aurora_secret_arn as it is no longer needed
}

# Upload Lambda zip to S3
resource "aws_s3_object" "lambda_package" {
  bucket = module.s3.bucket_name
  key    = "deploy/lambda.zip"
  source = "${path.root}/../../../build/lambda.zip"
  etag   = filemd5("${path.root}/../../../build/lambda.zip")
}

module "apigw_lambda" {
  source                 = "../../modules/apigw_lambda"
  project_name           = var.project_name
  environment            = var.environment
  query_lambda_role_arn  = module.iam.query_lambda_role_arn
  ingest_lambda_role_arn = module.iam.ingest_lambda_role_arn

  s3_bucket_name    = module.s3.bucket_name
  s3_key            = aws_s3_object.lambda_package.key
  s3_object_version = aws_s3_object.lambda_package.version_id

  lambda_env_vars = {
    ENVIRONMENT        = var.environment
    LOG_LEVEL          = "INFO"
    DATABASE_URL       = var.neon_connection_string
    S3_BUCKET          = module.s3.bucket_name
    OPENAI_API_KEY     = var.openai_api_key
    GEMINI_API_KEY     = var.gemini_api_key
    ANTHROPIC_API_KEY  = var.anthropic_api_key
    GROQ_API_KEY       = var.groq_api_key
    LLM_PROVIDER       = var.llm_provider
    LLM_ENABLED        = tostring(var.llm_enabled)
    EMBEDDING_PROVIDER = var.embedding_provider
  }
}

# ----------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------
output "api_url" {
  value = module.apigw_lambda.api_url
}

output "s3_bucket" {
  value = module.s3.bucket_name
}
