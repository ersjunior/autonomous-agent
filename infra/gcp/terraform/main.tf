terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_compute_network" "main" {
  name                    = "${var.project_name}-vpc"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "public" {
  count         = 2
  name          = "${var.project_name}-public-${count.index}"
  ip_cidr_range = "10.0.${count.index}.0/24"
  region        = var.region
  network       = google_compute_network.main.id
}

resource "google_compute_subnetwork" "private" {
  count                    = 2
  name                     = "${var.project_name}-private-${count.index}"
  ip_cidr_range            = "10.0.${count.index + 10}.0/24"
  region                   = var.region
  network                  = google_compute_network.main.id
  private_ip_google_access = true
}

resource "google_artifact_registry_repository" "main" {
  location      = var.region
  repository_id = var.project_name
  format        = "DOCKER"
}

resource "google_sql_database_instance" "postgres" {
  name             = "${var.project_name}-postgres"
  database_version = "POSTGRES_16"
  region           = var.region

  settings {
    tier = var.db_tier
    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.main.id
    }
  }

  deletion_protection = false
}

resource "google_sql_database" "main" {
  name     = var.db_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "main" {
  name     = var.db_username
  instance = google_sql_database_instance.postgres.name
  password = var.db_password
}

resource "google_redis_instance" "main" {
  name           = "${var.project_name}-redis"
  tier           = "BASIC"
  memory_size_gb = 1
  region         = var.region
  authorized_network = google_compute_network.main.id
  redis_version  = "REDIS_7_0"
}

resource "google_container_cluster" "main" {
  name     = "${var.project_name}-gke"
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1

  network    = google_compute_network.main.name
  subnetwork = google_compute_subnetwork.private[0].name

  ip_allocation_policy {}
}

resource "google_container_node_pool" "main" {
  name       = "${var.project_name}-pool"
  location   = var.region
  cluster    = google_container_cluster.main.name
  node_count = var.gke_node_count

  node_config {
    machine_type = var.gke_machine_type
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }
}

locals {
  common_env = {
    DATABASE_URL          = "postgresql://${var.db_username}:${var.db_password}@${google_sql_database_instance.postgres.private_ip_address}:5432/${var.db_name}"
    REDIS_URL             = "redis://${google_redis_instance.main.host}:6379/0"
    CELERY_BROKER_URL     = "redis://${google_redis_instance.main.host}:6379/1"
    CELERY_RESULT_BACKEND = "redis://${google_redis_instance.main.host}:6379/2"
  }
}
