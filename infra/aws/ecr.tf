resource "aws_ecr_repository" "api" {
  name                 = "${local.name}-api"
  image_tag_mutability = "MUTABLE"
  force_delete         = true # 테스트 → destroy 시 이미지째 삭제
  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "front" {
  name                 = "${local.name}-front"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

# 최근 이미지 10개만 유지(테스트 비용).
resource "aws_ecr_lifecycle_policy" "api" {
  repository = aws_ecr_repository.api.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep last 10"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 10 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "front" {
  repository = aws_ecr_repository.front.name
  policy     = aws_ecr_lifecycle_policy.api.policy
}
