# S3 bucket for document storage

variable "project_name" {
  type    = string
  default = "ragops"
}

variable "environment" {
  type    = string
  default = "dev"
}

# ----------------------------------------------------------------
# Document Storage Bucket
# ----------------------------------------------------------------
resource "aws_s3_bucket" "documents" {
  bucket = "${var.project_name}-${var.environment}-documents"

  tags = {
    Name        = "${var.project_name}-documents"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ----------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------
output "bucket_name" {
  value = aws_s3_bucket.documents.id
}

output "bucket_arn" {
  value = aws_s3_bucket.documents.arn
}
