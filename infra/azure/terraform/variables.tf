variable "region" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "autonomous-agent"
}

variable "db_password" {
  description = "PostgreSQL admin password"
  type        = string
  sensitive   = true
}

variable "db_username" {
  description = "PostgreSQL admin username"
  type        = string
  default     = "postgres"
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "autonomous_agent"
}

variable "db_sku_name" {
  description = "PostgreSQL flexible server SKU"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "redis_sku_name" {
  description = "Azure Cache for Redis SKU"
  type        = string
  default     = "Basic"
}

variable "image_tag" {
  description = "Container image tag"
  type        = string
  default     = "latest"
}

variable "aks_node_count" {
  description = "AKS default node pool size"
  type        = number
  default     = 2
}

variable "aks_vm_size" {
  description = "AKS node VM size"
  type        = string
  default     = "Standard_B2s"
}
