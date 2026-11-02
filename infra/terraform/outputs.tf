output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "registry_login_server" {
  value = azurerm_container_registry.this.login_server
}

output "registry_name" {
  value = azurerm_container_registry.this.name
}

output "app_url" {
  value = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "smokemonitor_url" {
  value = "https://${azurerm_container_app.smokemonitor.ingress[0].fqdn}"
}

output "jenkins_resource_group_name" {
  value = var.enable_jenkins ? azurerm_resource_group.jenkins[0].name : null
}
