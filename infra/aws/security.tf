# ALB: 웹(80) + api(8080) 인바운드. 테스트면 web_ingress_cidrs 를 사무실 IP로 좁히세요.
resource "aws_security_group" "alb" {
  name_prefix = "${local.name}-alb-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "front (http / redirect)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.web_ingress_cidrs
  }
  ingress {
    description = "https (front + api, host-based routing)"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.web_ingress_cidrs
  }
  ingress {
    description = "api http (only when enable_https=false)"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = var.web_ingress_cidrs
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-alb-sg" }

  lifecycle { create_before_destroy = true }
}

# api 태스크: ALB 로부터만 인바운드. 아웃바운드 전체(옴니솔 ERP·Gemini·ECR·RDS).
resource "aws_security_group" "api" {
  name_prefix = "${local.name}-api-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "from alb"
    from_port       = var.container_port_api
    to_port         = var.container_port_api
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-api-sg" }

  lifecycle { create_before_destroy = true }
}

resource "aws_security_group" "front" {
  name_prefix = "${local.name}-front-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "from alb"
    from_port       = var.container_port_front
    to_port         = var.container_port_front
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = { Name = "${local.name}-front-sg" }

  lifecycle { create_before_destroy = true }
}

# RDS: api 태스크로부터 5432 만.
resource "aws_security_group" "rds" {
  name_prefix = "${local.name}-rds-"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "postgres from api"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.api.id]
  }
  tags = { Name = "${local.name}-rds-sg" }

  lifecycle { create_before_destroy = true }
}
