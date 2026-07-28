variable "name" {
  type        = string
  description = "Stable system name used to scope infrastructure resources."
  default     = "lims-eln-reference"
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

