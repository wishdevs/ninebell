# 비밀값은 Secrets Manager 에 저장하고 태스크에 secrets 로 주입(이미지/평문 env 금지).

resource "random_password" "auth_secret" {
  length  = 48
  special = false
}

# DATABASE_URL = asyncpg 드라이버 + RDS 엔드포인트 + 생성 암호.
resource "aws_secretsmanager_secret" "db_url" {
  name                    = "${local.name}/DATABASE_URL"
  recovery_window_in_days = 0 # 테스트 → 즉시 삭제 가능
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s",
    var.db_username,
    random_password.db.result,
    aws_db_instance.postgres.address,
    var.db_name,
  )
}

resource "aws_secretsmanager_secret" "auth_secret" {
  name                    = "${local.name}/AUTH_SECRET"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "auth_secret" {
  secret_id     = aws_secretsmanager_secret.auth_secret.id
  secret_string = random_password.auth_secret.result
}

resource "aws_secretsmanager_secret" "gemini" {
  name                    = "${local.name}/GEMINI_API_KEY"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "gemini" {
  secret_id     = aws_secretsmanager_secret.gemini.id
  secret_string = var.gemini_api_key
}
