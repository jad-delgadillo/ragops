# IAM roles — least-privilege for Lambda functions

variable "project_name" {
  type    = string
  default = "ragops"
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 documents bucket"
  type        = string
}


# ----------------------------------------------------------------
# Lambda execution role — shared base
# ----------------------------------------------------------------
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# ----------------------------------------------------------------
# Query Lambda Role (read-only)
# ----------------------------------------------------------------
resource "aws_iam_role" "query_lambda" {
  name               = "${var.project_name}-${var.environment}-query-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Name        = "${var.project_name}-query-lambda-role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "query_lambda" {
  name = "${var.project_name}-${var.environment}-query-policy"
  role = aws_iam_role.query_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

# ----------------------------------------------------------------
# Ingest Lambda Role (S3 read + DB write)
# ----------------------------------------------------------------
resource "aws_iam_role" "ingest_lambda" {
  name               = "${var.project_name}-${var.environment}-ingest-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json

  tags = {
    Name        = "${var.project_name}-ingest-lambda-role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "ingest_lambda" {
  name = "${var.project_name}-${var.environment}-ingest-policy"
  role = aws_iam_role.ingest_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Sid    = "S3Read"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.s3_bucket_arn,
          "${var.s3_bucket_arn}/*"
        ]
      }
    ]
  })
}

# ----------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------
output "query_lambda_role_arn" {
  value = aws_iam_role.query_lambda.arn
}

output "ingest_lambda_role_arn" {
  value = aws_iam_role.ingest_lambda.arn
}
