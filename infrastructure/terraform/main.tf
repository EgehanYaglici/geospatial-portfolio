terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  default = "eu-central-1"
}

variable "project_prefix" {
  default = "egehan-geo"
}

variable "db_password" {
  sensitive = true
}

# --- S3 Bucket for static hosting & data ---
resource "aws_s3_bucket" "portfolio" {
  bucket = "${var.project_prefix}-web"
}

resource "aws_s3_bucket_website_configuration" "portfolio" {
  bucket = aws_s3_bucket.portfolio.id
  index_document { suffix = "index.html" }
  error_document { key = "error.html" }
}

resource "aws_s3_bucket_public_access_block" "portfolio" {
  bucket                  = aws_s3_bucket.portfolio.id
  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "portfolio_public" {
  bucket = aws_s3_bucket.portfolio.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "PublicReadGetObject"
      Effect    = "Allow"
      Principal = "*"
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.portfolio.arn}/*"
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.portfolio]
}

# --- S3 Bucket for raw/processed data ---
resource "aws_s3_bucket" "data" {
  bucket = "${var.project_prefix}-data"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- CloudFront Distribution ---
resource "aws_cloudfront_distribution" "portfolio" {
  origin {
    domain_name = aws_s3_bucket_website_configuration.portfolio.website_endpoint
    origin_id   = "S3-portfolio"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  enabled             = true
  default_root_object = "index.html"

  default_cache_behavior {
    allowed_methods  = ["GET", "HEAD"]
    cached_methods   = ["GET", "HEAD"]
    target_origin_id = "S3-portfolio"

    forwarded_values {
      query_string = false
      cookies { forward = "none" }
    }

    viewer_protocol_policy = "redirect-to-https"
    min_ttl                = 0
    default_ttl            = 3600
    max_ttl                = 86400
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}

# --- RDS PostgreSQL with PostGIS ---
resource "aws_db_instance" "postgis" {
  identifier     = "${var.project_prefix}-rds"
  engine         = "postgres"
  engine_version = "16"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "portfolio_gis"
  username = "gis_admin"
  password = var.db_password

  publicly_accessible    = false
  multi_az               = false
  skip_final_snapshot    = true
  deletion_protection    = false
  backup_retention_period = 1

  vpc_security_group_ids = [aws_security_group.rds.id]

  tags = {
    Project = "geospatial-portfolio"
  }
}

# --- Security Group for RDS ---
resource "aws_security_group" "rds" {
  name        = "${var.project_prefix}-rds-sg"
  description = "Allow PostgreSQL access from Lambda and local"

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # Restrict in production
    description = "PostgreSQL"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- Lambda for Spatial API ---
resource "aws_lambda_function" "spatial_api" {
  function_name = "${var.project_prefix}-spatial-api"
  runtime       = "python3.12"
  handler       = "handler.lambda_handler"
  timeout       = 30
  memory_size   = 256

  filename         = "${path.module}/lambda_placeholder.zip"
  source_code_hash = filebase64sha256("${path.module}/lambda_placeholder.zip")

  role = aws_iam_role.lambda_exec.arn

  environment {
    variables = {
      DB_HOST = aws_db_instance.postgis.address
      DB_PORT = "5432"
      DB_NAME = "portfolio_gis"
      DB_USER = "gis_admin"
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name = "${var.project_prefix}-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# --- API Gateway ---
resource "aws_apigatewayv2_api" "spatial" {
  name          = "${var.project_prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["Content-Type"]
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id             = aws_apigatewayv2_api.spatial.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.spatial_api.invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.spatial.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.spatial.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.spatial_api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.spatial.execution_arn}/*/*"
}

# --- Outputs ---
output "portfolio_url" {
  value = "https://${aws_cloudfront_distribution.portfolio.domain_name}"
}

output "api_url" {
  value = aws_apigatewayv2_api.spatial.api_endpoint
}

output "rds_endpoint" {
  value = aws_db_instance.postgis.endpoint
}

output "s3_data_bucket" {
  value = aws_s3_bucket.data.bucket
}
