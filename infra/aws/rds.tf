resource "aws_db_subnet_group" "main" {
  name       = "${local.name}-db"
  subnet_ids = aws_subnet.private[*].id
  tags       = { Name = "${local.name}-db-subnet" }
}

resource "random_password" "db" {
  length  = 24
  special = false # URL 인코딩 이슈 회피(테스트).
}

resource "aws_db_instance" "postgres" {
  identifier     = "${local.name}-pg"
  engine         = "postgres"
  engine_version = var.postgres_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_allocated_storage * 2 # 오토스케일 상한
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false # 테스트 → 단일 AZ

  backup_retention_period = 7
  deletion_protection     = false # 테스트 → 손쉽게 destroy. 운영은 true.
  skip_final_snapshot     = true  # 테스트. 운영은 false + final_snapshot_identifier.
  apply_immediately       = true

  tags = { Name = "${local.name}-pg" }
}
