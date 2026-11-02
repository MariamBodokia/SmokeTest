resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "this" {
  name     = "${var.project_name}-${random_string.suffix.result}"
  location = var.location
  tags = {
    project     = var.project_name
    environment = "poc"
    managed_by  = "terraform"
    cost_center = "learning"
  }
}

resource "azurerm_resource_group" "jenkins" {
  count    = var.enable_jenkins ? 1 : 0
  name     = var.jenkins_resource_group_name
  location = var.location
  tags = {
    project     = var.project_name
    environment = "poc"
    managed_by  = "terraform"
    component   = "jenkins"
  }
}

resource "azurerm_consumption_budget_resource_group" "this" {
  name              = "${var.project_name}-monthly-budget"
  resource_group_id = azurerm_resource_group.this.id
  amount            = var.cost_budget_usd
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start_date
    end_date   = var.budget_end_date
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.cost_alert_email == "" ? [] : [var.cost_alert_email]
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.cost_alert_email == "" ? [] : [var.cost_alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = var.cost_alert_email == "" ? [] : [var.cost_alert_email]
  }
}

resource "azurerm_log_analytics_workspace" "this" {
  name                = "${var.project_name}-logs-${random_string.suffix.result}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "this" {
  name                = replace("${var.project_name}${random_string.suffix.result}", "-", "")
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Basic"
  admin_enabled       = true
}

locals {
  effective_container_image = var.container_image == "" ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : var.container_image
}

resource "azurerm_container_app_environment" "this" {
  name                       = "${var.project_name}-env"
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.this.id
  tags = {
    project     = var.project_name
    environment = "poc"
  }
}

resource "azurerm_container_app" "app" {
  name                         = "${var.project_name}-app"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"

  ingress {
    external_enabled = true
    target_port      = var.container_target_port
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  secret {
    name  = "admin-token"
    value = var.admin_token
  }

  secret {
    name  = "registry-password"
    value = azurerm_container_registry.this.admin_password
  }

  registry {
    server               = azurerm_container_registry.this.login_server
    username             = azurerm_container_registry.this.admin_username
    password_secret_name = "registry-password"
  }

  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name   = "app"
      image  = local.effective_container_image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name        = "ADMIN_TOKEN"
        secret_name = "admin-token"
      }
    }
  }

}
