output "front_url" {
  description = "웹 접속 URL"
  value       = var.enable_https ? "https://${var.domain_name}" : "http://${aws_lb.main.dns_name}"
}

output "api_url" {
  description = "API URL (front 이미지 빌드 시 NEXT_PUBLIC_API_BASE 로 사용)"
  value       = var.enable_https ? "https://${var.api_domain_name}" : "http://${aws_lb.main.dns_name}:8080"
}

output "dns_records_needed" {
  description = "https 모드: hynro.com DNS 에 추가할 CNAME (→ ALB). ACM 검증 레코드는 별도(README)."
  value = var.enable_https ? {
    "${var.domain_name}"     = aws_lb.main.dns_name
    "${var.api_domain_name}" = aws_lb.main.dns_name
  } : {}
}

output "alb_dns" {
  value = aws_lb.main.dns_name
}

output "ecr_api_repo" {
  value = aws_ecr_repository.api.repository_url
}

output "ecr_front_repo" {
  value = aws_ecr_repository.front.repository_url
}

output "rds_endpoint" {
  value = aws_db_instance.postgres.address
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
