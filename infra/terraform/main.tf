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
  location = var.jenkins_location
  tags = {
    project     = var.project_name
    environment = "poc"
    managed_by  = "terraform"
    component   = "jenkins"
  }
}

resource "azurerm_public_ip" "jenkins" {
  count               = var.enable_jenkins ? 1 : 0
  name                = "smokemonitor-jenkins-ip"
  location            = azurerm_resource_group.jenkins[0].location
  resource_group_name = azurerm_resource_group.jenkins[0].name
  allocation_method   = "Static"
  sku                 = "Standard"
}

resource "azurerm_network_security_group" "jenkins" {
  count               = var.enable_jenkins ? 1 : 0
  name                = "smokemonitor-jenkins-nsg"
  location            = azurerm_resource_group.jenkins[0].location
  resource_group_name = azurerm_resource_group.jenkins[0].name

  security_rule {
    name                       = "jenkins-http-from-admin"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "8080"
    source_address_prefix      = var.jenkins_allowed_cidr
    destination_address_prefix = "*"
  }

  security_rule {
    name                       = "ssh-from-admin"
    priority                   = 110
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = var.jenkins_allowed_cidr
    destination_address_prefix = "*"
  }
}

resource "azurerm_network_interface" "jenkins" {
  count               = var.enable_jenkins ? 1 : 0
  name                = "smokemonitor-jenkins-nic"
  location            = azurerm_resource_group.jenkins[0].location
  resource_group_name = azurerm_resource_group.jenkins[0].name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.jenkins[0].id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.jenkins[0].id
  }
}

resource "azurerm_network_interface_security_group_association" "jenkins" {
  count                     = var.enable_jenkins ? 1 : 0
  network_interface_id      = azurerm_network_interface.jenkins[0].id
  network_security_group_id = azurerm_network_security_group.jenkins[0].id
}

resource "azurerm_virtual_network" "jenkins" {
  count               = var.enable_jenkins ? 1 : 0
  name                = "smokemonitor-jenkins-vnet"
  location            = azurerm_resource_group.jenkins[0].location
  resource_group_name = azurerm_resource_group.jenkins[0].name
  address_space       = ["10.40.0.0/16"]
}

resource "azurerm_subnet" "jenkins" {
  count                = var.enable_jenkins ? 1 : 0
  name                 = "default"
  resource_group_name  = azurerm_resource_group.jenkins[0].name
  virtual_network_name = azurerm_virtual_network.jenkins[0].name
  address_prefixes     = ["10.40.1.0/24"]
}

resource "azurerm_linux_virtual_machine" "jenkins" {
  count                           = var.enable_jenkins ? 1 : 0
  name                            = "smokemonitor-jenkins"
  resource_group_name             = azurerm_resource_group.jenkins[0].name
  location                        = azurerm_resource_group.jenkins[0].location
  size                            = "Standard_D2ads_v5"
  admin_username                  = var.jenkins_admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.jenkins[0].id]

  admin_ssh_key {
    username   = var.jenkins_admin_username
    public_key = var.jenkins_ssh_public_key
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
    disk_size_gb         = 30
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
  }

  custom_data = base64encode(<<-CLOUDINIT
    #cloud-config
    package_update: true
    packages:
      - docker.io
      - docker-compose-v2
    runcmd:
      - usermod -aG docker ${var.jenkins_admin_username}
      - mkdir -p /opt/jenkins_home
      - chown -R 1000:1000 /opt/jenkins_home
      - |
        cat > /opt/jenkins-compose.yml <<'EOF'
        services:
          jenkins:
            image: jenkins/jenkins:2.440.3-lts-jdk17
            restart: unless-stopped
            ports:
              - "8080:8080"
              - "50000:50000"
            volumes:
              - /opt/jenkins_home:/var/jenkins_home
            environment:
              JAVA_OPTS: "-Djenkins.install.runSetupWizard=true"
        EOF
      - systemctl enable --now docker
      - docker compose -f /opt/jenkins-compose.yml up -d
      - |
        until docker compose -f /opt/jenkins-compose.yml exec -T jenkins test -f /var/jenkins_home/secrets/initialAdminPassword; do sleep 5; done
        docker compose -f /opt/jenkins-compose.yml exec -T jenkins bash -c 'mkdir -p /var/jenkins_home/plugins && curl -fsSL -o /var/jenkins_home/plugins/monitor-pro.jpi https://updates.jenkins.io/download/plugins/monitor-pro/1.0.9/monitor-pro.hpi && chown 1000:1000 /var/jenkins_home/plugins/monitor-pro.jpi'
        docker compose -f /opt/jenkins-compose.yml restart jenkins
  CLOUDINIT
  )
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

resource "azurerm_storage_account" "monitor" {
  name                     = replace("${var.project_name}${random_string.suffix.result}data", "-", "")
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
}

resource "azurerm_storage_table" "monitor" {
  name                 = "smoketestruns"
  storage_account_name = azurerm_storage_account.monitor.name
}

locals {
  effective_container_image    = var.container_image == "" ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : var.container_image
  effective_smokemonitor_image = var.smokemonitor_image == "" ? "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest" : var.smokemonitor_image
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

resource "azurerm_container_app" "smokemonitor" {
  name                         = "${var.project_name}-monitor"
  container_app_environment_id = azurerm_container_app_environment.this.id
  resource_group_name          = azurerm_resource_group.this.name
  revision_mode                = "Single"

  ingress {
    external_enabled = true
    target_port      = var.smokemonitor_target_port
    transport        = "http"
    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  secret {
    name  = "monitor-token"
    value = var.admin_token
  }

  secret {
    name  = "registry-password"
    value = azurerm_container_registry.this.admin_password
  }

  secret {
    name  = "storage-connection-string"
    value = azurerm_storage_account.monitor.primary_connection_string
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
      name   = "smokemonitor"
      image  = local.effective_smokemonitor_image
      cpu    = 0.25
      memory = "0.5Gi"
      env {
        name        = "SMOKEMONITOR_TOKEN"
        secret_name = "monitor-token"
      }
      env {
        name  = "DATABASE_PATH"
        value = "/tmp/smokemonitor.db"
      }
      env {
        name        = "AZURE_STORAGE_CONNECTION_STRING"
        secret_name = "storage-connection-string"
      }
      env {
        name  = "AZURE_STORAGE_TABLE"
        value = azurerm_storage_table.monitor.name
      }
    }
  }
}
