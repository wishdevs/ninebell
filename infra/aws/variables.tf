variable "project" {
  type    = string
  default = "ninebell-dashboard"
}

variable "env" {
  type    = string
  default = "test"
}

variable "region" {
  type    = string
  default = "ap-northeast-2" # 서울
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

# ALB(웹) 접근을 허용할 CIDR. 테스트면 사무실 공인 IP/32 로 좁히길 권장.
variable "web_ingress_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

# ── 컨테이너 이미지(ECR 에 push 후 태그) ─────────────────────────────────────
variable "api_image_tag" {
  type    = string
  default = "latest"
}

variable "front_image_tag" {
  type    = string
  default = "latest"
}

# ── Fargate 태스크 사이즈(10 동접 테스트 기준) ───────────────────────────────
# api = FastAPI + Playwright(헤드리스 Chromium). 브라우저 1개 ~0.6~1.0GB → 여유 있게.
variable "api_cpu" {
  type    = number
  default = 4096 # 4 vCPU
}

variable "api_memory" {
  type    = number
  default = 16384 # 16 GB
}

variable "api_desired_count" {
  type    = number
  default = 1 # ⚠ 인메모리 세션 상태 → 1 유지(수평 확장은 Redis 외부화 필요).
}

variable "front_cpu" {
  type    = number
  default = 1024 # 1 vCPU
}

variable "front_memory" {
  type    = number
  default = 2048 # 2 GB (pm2 2 프로세스, 런타임만 — 빌드는 CI에서)
}

variable "front_desired_count" {
  type    = number
  default = 1
}

# X86_64 권장(Chromium 호환 안전). 비용 절감하려면 ARM64 + arm 베이스 이미지로.
variable "cpu_architecture" {
  type    = string
  default = "X86_64"
}

# ── 동시 실행 상한(세마포어). 10 동접 테스트 → 브라우저 6개 동시로 시작 ──────
variable "max_concurrent_erp_runs" {
  type    = number
  default = 6
}

variable "max_concurrent_erp_logins" {
  type    = number
  default = 3
}

# ── RDS ──────────────────────────────────────────────────────────────────────
variable "db_instance_class" {
  type    = string
  default = "db.t4g.medium" # 2 vCPU / 4GB (테스트). 필요시 상향.
}

variable "db_allocated_storage" {
  type    = number
  default = 50
}

variable "postgres_version" {
  type = string
  # 사용 가능 버전 확인:
  # aws rds describe-db-engine-versions --engine postgres --query 'DBEngineVersions[].EngineVersion'
  default = "17.4"
}

variable "db_name" {
  type    = string
  default = "dashboard"
}

variable "db_username" {
  type    = string
  default = "dashboard"
}

# ── 앱 설정 ──────────────────────────────────────────────────────────────────
variable "erp_base" {
  type    = string
  default = "https://erp.ninebell.co.kr"
}

variable "gemini_model" {
  type    = string
  default = "gemini-2.5-flash"
}

# 비밀값(적용 시 -var 또는 tfvars 로 주입. tfvars 는 커밋 금지).
variable "gemini_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "container_port_api" {
  type    = number
  default = 8000
}

variable "container_port_front" {
  type    = number
  default = 3000
}

# 헤드리스 Chromium 실행 인자 → 앱이 CHROMIUM_ARGS env 로 읽어 launch(args=...).
# Fargate 는 /dev/shm 조절 불가라 아래 두 플래그 필수(기본값 유지 권장).
variable "chromium_args" {
  type    = string
  default = "--disable-dev-shm-usage --no-sandbox"
}

# ── HTTPS / 도메인 ───────────────────────────────────────────────────────────
# enable_https=true 로 켜면: ALB 443 리스너(호스트 기반) + 80→443 리다이렉트. 8080(http api) 비활성.
# 사전: ACM 인증서(서울 ap-northeast-2)에 domain_name·api_domain_name 둘 다 포함(또는 *.hynro.com)하고
#       ISSUED 상태여야 함. acm_certificate_arn 에 그 ARN 주입. DNS 설정은 README 참조.
variable "enable_https" {
  type    = bool
  default = false
}

variable "acm_certificate_arn" {
  type    = string
  default = ""
}

variable "domain_name" {
  type    = string
  default = "ninebell.hynro.com" # front
}

variable "api_domain_name" {
  type    = string
  default = "ninebell-api.hynro.com" # api
}

variable "ssl_policy" {
  type    = string
  default = "ELBSecurityPolicy-TLS13-1-2-2021-06"
}
