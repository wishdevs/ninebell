resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "disabled" # 테스트 비용. 운영은 enabled 권장.
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${local.name}/api"
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "front" {
  name              = "/ecs/${local.name}/front"
  retention_in_days = 14
}

data "aws_region" "current" {}

# ── API 태스크 (FastAPI + Playwright) ────────────────────────────────────────
# ⚠ uvicorn 1 프로세스(멀티 워커 금지 — 인메모리 SSE/세마포어 상태).
# ⚠ initProcessEnabled=true → Chromium 자식 프로세스 좀비 회수.
# ⚠ Fargate 는 /dev/shm 조절 불가 → 앱이 Chromium 을 --disable-dev-shm-usage --no-sandbox 로 띄워야 함.
resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.api_image_tag}"
    essential = true

    command = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", tostring(var.container_port_api)]

    linuxParameters = { initProcessEnabled = true }

    portMappings = [{ containerPort = var.container_port_api, protocol = "tcp" }]

    environment = [
      { name = "ERP_BASE", value = var.erp_base },
      { name = "GEMINI_MODEL", value = var.gemini_model },
      { name = "MAX_CONCURRENT_ERP_RUNS", value = tostring(var.max_concurrent_erp_runs) },
      { name = "MAX_CONCURRENT_ERP_LOGINS", value = tostring(var.max_concurrent_erp_logins) },
      { name = "CHROMIUM_ARGS", value = var.chromium_args }, # Fargate /dev/shm 회피 플래그
      { name = "DEV_CREATE_ALL", value = var.dev_create_all },
      { name = "TZ", value = "Asia/Seoul" },
      { name = "PYTHONUNBUFFERED", value = "1" },
    ]

    secrets = [
      { name = "DATABASE_URL", valueFrom = aws_secretsmanager_secret.db_url.arn },
      { name = "AUTH_SECRET", valueFrom = aws_secretsmanager_secret.auth_secret.arn },
      { name = "GEMINI_API_KEY", valueFrom = aws_secretsmanager_secret.gemini.arn },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.api.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "api"
      }
    }
  }])
}

# ── Front 태스크 (Next.js, pm2 2 프로세스) ───────────────────────────────────
# 무상태라 pm2 클러스터 2개 OK. CMD 는 이미지(front.Dockerfile)의 pm2-runtime.
resource "aws_ecs_task_definition" "front" {
  family                   = "${local.name}-front"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.front_cpu
  memory                   = var.front_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.cpu_architecture
  }

  container_definitions = jsonencode([{
    name         = "front"
    image        = "${aws_ecr_repository.front.repository_url}:${var.front_image_tag}"
    essential    = true
    portMappings = [{ containerPort = var.container_port_front, protocol = "tcp" }]

    environment = [
      { name = "NODE_ENV", value = "production" },
      { name = "PORT", value = tostring(var.container_port_front) },
      { name = "TZ", value = "Asia/Seoul" },
      # ⚠ NEXT_PUBLIC_API_BASE 는 빌드 타임에 번들로 구워짐 → 여기 런타임 env 는 SSR 용 참고값.
      #   클라이언트가 쓰는 값은 front 이미지 빌드 시 --build-arg 로 주입해야 함(README 참조).
      { name = "NEXT_PUBLIC_API_BASE", value = var.enable_https ? "https://${var.api_domain_name}" : "http://${aws_lb.main.dns_name}:8080" },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.front.name
        "awslogs-region"        = data.aws_region.current.name
        "awslogs-stream-prefix" = "front"
      }
    }
  }])
}

# ── 서비스 ───────────────────────────────────────────────────────────────────
resource "aws_ecs_service" "api" {
  name                               = "api"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.api.arn
  desired_count                      = var.api_desired_count
  launch_type                        = "FARGATE"
  health_check_grace_period_seconds  = 180 # Playwright 컨테이너 워밍업 여유
  deployment_minimum_healthy_percent = 0   # 태스크 1개라 롤링 시 잠깐 0 허용(테스트)
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = true # 퍼블릭 서브넷 + 공인 IP = NAT 없이 인터넷(ERP/Gemini/ECR)
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = var.container_port_api
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "front" {
  name            = "front"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.front.arn
  desired_count   = var.front_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.front.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.front.arn
    container_name   = "front"
    container_port   = var.container_port_front
  }

  depends_on = [aws_lb_listener.http]
}
