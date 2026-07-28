variable "name" {
  type        = string
  description = "Stable system name used to scope infrastructure resources."
  default     = "lims-eln-reference"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.name))
    error_message = "System name requires 3..32 lower-case alphanumeric or hyphen characters."
  }
}

variable "organization" {
  type        = string
  description = "Stable organization segment for hierarchical runtime resources."
  default     = "example-laboratory"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.organization))
    error_message = "Organization requires 3..32 lower-case alphanumeric or hyphen characters."
  }
}

variable "environment" {
  type        = string
  description = "Named deployment environment carried in resource paths and tags."
  default     = "sandbox"

  validation {
    condition     = contains(["sandbox", "development", "test", "qualification", "production"], var.environment)
    error_message = "Environment requires an approved lifecycle value."
  }
}

variable "vendor_base_url" {
  type        = string
  description = "Non-sensitive vendor endpoint stored in Parameter Store."
  default     = "https://synthetic-vendor.invalid"

  validation {
    condition     = can(regex("^https://", var.vendor_base_url))
    error_message = "Vendor endpoint requires HTTPS."
  }
}

variable "vendor_timeout_seconds" {
  type        = number
  description = "Non-sensitive outbound request timeout stored in Parameter Store."
  default     = 15

  validation {
    condition     = var.vendor_timeout_seconds >= 1 && var.vendor_timeout_seconds <= 60
    error_message = "Vendor timeout requires a value from 1 through 60 seconds."
  }
}

variable "evidence_retention_days" {
  type        = number
  description = "Approved retention period for immutable evidence objects."
  default     = 2555

  validation {
    condition     = var.evidence_retention_days >= 365
    error_message = "Evidence retention requires at least 365 days."
  }
}

variable "recovery_transition_days" {
  type        = number
  description = "Days before backup objects transition to archival storage."
  default     = 90
}
