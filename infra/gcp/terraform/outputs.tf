output "gke_cluster_name" {
  value = google_container_cluster.main.name
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}"
}

output "cloudsql_private_ip" {
  value = google_sql_database_instance.postgres.private_ip_address
}

output "memorystore_host" {
  value = google_redis_instance.main.host
}

output "memorystore_port" {
  value = google_redis_instance.main.port
}
