locals {
  runtime_scope = "${var.organization}/${var.name}/${var.environment}"
  runtime_tags = {
    Application = var.name
    Environment = var.environment
    ManagedBy   = "terraform"
    Purpose     = "runtime-configuration"
  }
  runtime_parameters = {
    vendor_base_url = {
      logical_name = "vendor.base_url"
      name         = "/${local.runtime_scope}/config/vendor-base-url"
      value        = var.vendor_base_url
    }
    vendor_timeout_seconds = {
      logical_name = "vendor.timeout_seconds"
      name         = "/${local.runtime_scope}/config/vendor-timeout-seconds"
      value        = tostring(var.vendor_timeout_seconds)
    }
  }
  runtime_secrets = {
    vendor_credentials = {
      logical_name = "vendor.credentials"
      name         = "${local.runtime_scope}/vendor-credentials"
    }
  }
}

resource "aws_kms_key" "runtime_secrets" {
  description             = "${var.name} runtime secret encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true

  tags = local.runtime_tags
}

resource "aws_kms_alias" "runtime_secrets" {
  name          = "alias/${var.name}-${var.environment}-runtime-secrets"
  target_key_id = aws_kms_key.runtime_secrets.key_id
}

resource "aws_ssm_parameter" "runtime_configuration" {
  for_each = local.runtime_parameters

  name  = each.value.name
  type  = "String"
  value = each.value.value

  tags = merge(local.runtime_tags, {
    Classification = "configuration"
  })
}

resource "aws_secretsmanager_secret" "runtime" {
  for_each = local.runtime_secrets

  name                    = each.value.name
  description             = "${var.name} ${each.key} runtime secret"
  kms_key_id              = aws_kms_key.runtime_secrets.arn
  recovery_window_in_days = 30

  tags = merge(local.runtime_tags, {
    Classification = "secret"
  })
}

data "aws_iam_policy_document" "runtime_configuration_read" {
  statement {
    sid       = "ReadNamedRuntimeConfiguration"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [for parameter in aws_ssm_parameter.runtime_configuration : parameter.arn]
  }

  statement {
    sid       = "ReadNamedRuntimeSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [for secret in aws_secretsmanager_secret.runtime : secret.arn]
  }

  statement {
    sid       = "DecryptRuntimeSecretsThroughSecretsManager"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.runtime_secrets.arn]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values = [
        "secretsmanager.${data.aws_region.current.name}.${data.aws_partition.current.dns_suffix}"
      ]
    }

    condition {
      test     = "ForAnyValue:StringEquals"
      variable = "kms:EncryptionContext:SecretARN"
      values   = [for secret in aws_secretsmanager_secret.runtime : secret.arn]
    }
  }
}

resource "aws_iam_policy" "runtime_configuration_read" {
  name        = "${var.name}-${var.environment}-runtime-read"
  description = "Read the named runtime configuration and secret resources."
  policy      = data.aws_iam_policy_document.runtime_configuration_read.json

  tags = local.runtime_tags
}

output "runtime_setting_catalog" {
  description = "Value-free runtime catalog for application composition."
  value = {
    schema_version = "1.0.0"
    aws_scope = {
      partition  = data.aws_partition.current.partition
      region     = data.aws_region.current.name
      account_id = data.aws_caller_identity.current.account_id
    }
    settings = concat(
      [
        for catalog_key, parameter in aws_ssm_parameter.runtime_configuration : {
          logical_name       = local.runtime_parameters[catalog_key].logical_name
          classification     = "configuration"
          source             = "parameter_store"
          resource_arn       = parameter.arn
          cache_ttl_seconds  = 900
          parameter_version  = parameter.version
        }
      ],
      [
        for catalog_key, secret in aws_secretsmanager_secret.runtime : {
          logical_name          = local.runtime_secrets[catalog_key].logical_name
          classification        = "secret"
          source                = "secrets_manager"
          resource_arn          = secret.arn
          cache_ttl_seconds     = 300
          secret_version_stage  = "AWSCURRENT"
        }
      ]
    )
  }
}

output "runtime_read_policy_arn" {
  description = "Least-privilege policy for the workload identity."
  value       = aws_iam_policy.runtime_configuration_read.arn
}
