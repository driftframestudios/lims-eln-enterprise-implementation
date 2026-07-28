data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

resource "aws_kms_key" "evidence" {
  description             = "${var.name} evidence encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/${var.name}-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}

resource "aws_s3_bucket" "evidence" {
  bucket_prefix = "${var.name}-evidence-"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.evidence.arn
      sse_algorithm     = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  depends_on = [aws_s3_bucket_versioning.evidence]
  bucket     = aws_s3_bucket.evidence.id

  rule {
    id     = "retain-and-archive-evidence"
    status = "Enabled"

    filter {}

    transition {
      days          = var.recovery_transition_days
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = var.evidence_retention_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.evidence_retention_days
    }
  }
}

resource "aws_backup_vault" "laboratory" {
  name        = "${var.name}-recovery"
  kms_key_arn = aws_kms_key.evidence.arn
}

resource "aws_cloudwatch_log_group" "application" {
  name              = "/${var.name}/application"
  retention_in_days = 365
  kms_key_id        = aws_kms_key.evidence.arn
}

output "evidence_bucket" {
  value = aws_s3_bucket.evidence.id
}

output "backup_vault" {
  value = aws_backup_vault.laboratory.name
}
