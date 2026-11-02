variable "subscription_id" {
  description = "Azure subscription ID. Supply through TF_VAR_subscription_id."
  type        = string
  sensitive   = true
}

variable "location" {
  description = "Azure region for the POC."
  type        = string
  default     = "westeurope"
}

variable "project_name" {
  description = "Globally unique short project name."
  type        = string
  default     = "smokemonitor"
}

variable "admin_token" {
  description = "Token for the demo app admin API."
  type        = string
  sensitive   = true
}

variable "container_image" {
  description = "Fully qualified demo application image."
  type        = string
  default     = ""
}

variable "container_target_port" {
  description = "Port exposed by the currently deployed container image."
  type        = number
  default     = 80
}

variable "smokemonitor_image" {
  description = "Fully qualified SmokeMonitor image."
  type        = string
  default     = ""
}

variable "smokemonitor_target_port" {
  description = "Port exposed by the SmokeMonitor image."
  type        = number
  default     = 80
}

variable "cost_budget_usd" {
  description = "Monthly resource-group budget in USD. This sends alerts; it does not stop resources."
  type        = number
  default     = 150
}

variable "budget_start_date" {
  description = "UTC start date for the monthly budget period."
  type        = string
  default     = "2026-11-01T00:00:00Z"
}

variable "budget_end_date" {
  description = "UTC end date for the monthly budget period."
  type        = string
  default     = "2027-11-01T00:00:00Z"
}

variable "cost_alert_email" {
  description = "Optional email address for budget alerts."
  type        = string
  default     = ""
}

variable "enable_jenkins" {
  description = "Create the separate Jenkins resource group. Jenkins resources are added in a later milestone."
  type        = bool
  default     = false
}

variable "jenkins_resource_group_name" {
  description = "Resource group name reserved for Jenkins infrastructure."
  type        = string
  default     = "smokemonitor-jenkins"
}
