# AWS 테스트 배포 (ECS Fargate + RDS) — 나인벨 대시보드

10 동접 테스트용 IaC. **api(FastAPI+Playwright)** + **front(Next.js, pm2 2프로세스)** 를 ECS Fargate 로,
**PostgreSQL** 을 RDS 로 올립니다. ALB 는 `:80 → front`, `:8080 → api` 로 분리(도메인 없이 테스트).

```
Internet ──► ALB ─┬─ :80  ──► front 서비스 (Next.js, pm2 x2)
                  └─ :8080 ──► api  서비스 (uvicorn 1p + Chromium N)
                                   └──► RDS PostgreSQL (프라이빗)
```

## ⚠ 이 앱에서 반드시 지킬 것 (안 지키면 배포는 되는데 런타임에 깨짐)

1. **api 는 uvicorn 1 프로세스.** gunicorn/uvicorn 멀티 워커 금지 — 라이브 실행 상태(SSE 버퍼·커서·
   세마포어·브라우저 팩토리)가 **프로세스 인메모리**라 워커가 갈리면 세션을 못 찾고 동시성 상한이 뻥튀기됨.
   더 뽑아야 하면 워커가 아니라 **Redis 외부화 + ECS 태스크 수평 확장**. (Next 는 무상태라 pm2 2개 OK.)

2. **Fargate 는 `/dev/shm` 크기 조절 불가** → Chromium 이 랜덤 크래시(`Target closed`).
   → **이미 반영됨**: 앱이 `CHROMIUM_ARGS` env 를 읽어 `launch(args=...)` 하고(`config.chromium_args`),
   TF 가 api 태스크에 `CHROMIUM_ARGS="--disable-dev-shm-usage --no-sandbox"` 를 주입합니다(`var.chromium_args`).
   로컬 dev 는 env 없음 → 기본 동작 유지. (EC2 launch type 면 `shmSize` 로 대체 가능.)

3. **NEXT_PUBLIC_API_BASE 는 빌드 타임 값** — Next 클라이언트 번들에 구워집니다. 런타임 env 로는 못 바꿔요.
   → front 이미지를 **`--build-arg NEXT_PUBLIC_API_BASE=http://<ALB_DNS>:8080` 로 빌드**해야 함(2단계 배포).

4. **CORS** — front(`http://<alb>`)가 api(`http://<alb>:8080`)를 부르면 교차 출처. api 의 CORS 허용 오리진에
   front URL 을 넣어야 합니다(`backend/app` CORS 설정/ENV 확인).

5. **SSE** — ALB `idle_timeout=4000`(TF에 반영). 도메인/프록시 추가 시 버퍼링 off 유지.

## 사전 준비
- terraform ≥ 1.6, aws-cli(자격증명), docker
- `cp terraform.tfvars.example terraform.tfvars` 후 `gemini_api_key` 등 채우기 (**tfvars 커밋 금지**)
- RDS 버전 확인: `aws rds describe-db-engine-versions --engine postgres --query 'DBEngineVersions[].EngineVersion' --output text`

## 배포 순서 (2단계)

```bash
cd infra/aws
terraform init
terraform apply            # ① 인프라 생성(ECR·ALB·RDS·ECS). 이미지 없어 서비스는 아직 unhealthy — 정상.

# ② 출력 확인
API_URL=$(terraform output -raw api_url)      # http://<alb>:8080
API_REPO=$(terraform output -raw ecr_api_repo)
FRONT_REPO=$(terraform output -raw ecr_front_repo)
REGION=ap-northeast-2
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)

# ECR 로그인
aws ecr get-login-password --region ap-northeast-2 \
  | docker login --username AWS --password-stdin ${ACCOUNT}.dkr.ecr.ap-northeast-2.amazonaws.com

# ③ api 이미지 (컨텍스트 = 리포 루트)
cd ../../   # 리포 루트
docker build -f infra/aws/docker/api.Dockerfile -t ${API_REPO}:latest .
docker push ${API_REPO}:latest

# ④ front 이미지 — NEXT_PUBLIC_API_BASE 를 빌드 타임에 주입!
docker build -f infra/aws/docker/front.Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE="${API_URL}" \
  -t ${FRONT_REPO}:latest .
docker push ${FRONT_REPO}:latest

# ⑤ DB 마이그레이션 (1회) — 아래 "마이그레이션" 참조

# ⑥ 새 이미지로 서비스 롤아웃
aws ecs update-service --cluster ninebell-dashboard-test --service api   --force-new-deployment --region ap-northeast-2
aws ecs update-service --cluster ninebell-dashboard-test --service front --force-new-deployment --region ap-northeast-2
```

접속: `terraform output front_url`.

## 마이그레이션 (alembic)
서비스가 아니라 **1회성 태스크**로 실행(권장):
```bash
# api 태스크 정의로 command 오버라이드해 1회 실행
aws ecs run-task --cluster ninebell-dashboard-test \
  --task-definition ninebell-dashboard-test-api --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<public-subnet-id>],securityGroups=[<api-sg-id>],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"api","command":["alembic","upgrade","head"]}]}' \
  --region ap-northeast-2
```
서브넷/보안그룹 ID 는 콘솔 또는 `terraform state show` 로 확인. (부트스트랩 admin/시드가 startup 에서 도는지
`app/main.py` 확인 — 안 돌면 별도 시드 태스크 필요.)

## 확인
```bash
curl -i "$(terraform output -raw api_url)/openapi.json"   # 200
open "$(terraform output -raw front_url)"
```
로그: CloudWatch `/ecs/ninebell-dashboard-test/api`, `/front`.

## 스케일 메모 (10 동접 테스트 기준)
- `max_concurrent_erp_runs=6` 로 시작 → 브라우저 6개 동시. api 태스크 4vCPU/16GB 면 여유.
- **실제 상한은 옴니솔(ERP) 동시 세션 허용치** — 먼저 확인. 낮으면 세마포어를 그 이하로.
- 더 키우려면: ① api_cpu/api_memory 상향 + runs 상향, ② 그다음이 워커 풀 + Redis(수평).

## HTTPS / 도메인 (ninebell.hynro.com)

`enable_https=true` 로 켜면 ALB 가 **호스트 기반**으로 라우팅합니다:
- `https://ninebell.hynro.com` → front
- `https://ninebell-api.hynro.com` → api
- `http://…`(80) → 443 자동 리다이렉트 · 8080(http) 리스너는 비활성

### 도메인(hynro.com DNS)에서 설정할 것 — 2가지
> hynro.com 을 관리하는 DNS(가비아/Cloudflare/Route53 등) 콘솔에서 합니다.

**① ACM 인증서 발급 — ⚠ 리전은 서울(ap-northeast-2), ALB 와 동일해야 함**
1. ACM 콘솔(ap-northeast-2) → *인증서 요청(퍼블릭)* → 도메인 이름에 **둘 다** 추가:
   `ninebell.hynro.com`, `ninebell-api.hynro.com`  *(또는 `*.hynro.com` 와일드카드 하나로 둘 다 커버)*
2. 검증 방법 = **DNS**. ACM 이 도메인별 **CNAME 검증 레코드**(이름/값)를 줍니다.
3. 그 **CNAME 검증 레코드를 hynro.com DNS 에 추가** → 몇 분 뒤 상태가 **ISSUED**.
4. 발급된 **인증서 ARN** 복사.

**② ALB 로 향하는 CNAME 레코드 2개**
`terraform output alb_dns` 로 ALB 주소(예: `ninebell-dashboard-test-alb-123.ap-northeast-2.elb.amazonaws.com`) 확인 후, hynro.com DNS 에:

| 타입 | 이름 | 값 |
|---|---|---|
| CNAME | `ninebell.hynro.com` | `<ALB DNS>` |
| CNAME | `ninebell-api.hynro.com` | `<ALB DNS>` |

(Route53 라면 CNAME 대신 A/ALIAS 권장. 서브도메인이라 CNAME 도 정상.)
→ `terraform output dns_records_needed` 가 이 2개를 그대로 뽑아줍니다.

### 적용 순서
```bash
# 1) 먼저 http 모드로 apply → ALB DNS 확보
terraform apply
terraform output alb_dns          # ② CNAME 값

# 2) 위 ①ACM 인증서 발급 + ②CNAME 2개 등록 (DNS 전파 대기)

# 3) https 모드로 재적용
terraform apply -var enable_https=true -var acm_certificate_arn="arn:aws:acm:ap-northeast-2:<acct>:certificate/xxxx"

# 4) front 이미지를 https api 주소로 재빌드 + push + 롤아웃
docker build -f infra/aws/docker/front.Dockerfile \
  --build-arg NEXT_PUBLIC_API_BASE="https://ninebell-api.hynro.com" \
  -t ${FRONT_REPO}:latest .
docker push ${FRONT_REPO}:latest
aws ecs update-service --cluster ninebell-dashboard-test --service front --force-new-deployment --region ap-northeast-2
```

접속: `https://ninebell.hynro.com`. (api CORS 허용 오리진에 `https://ninebell.hynro.com` 포함 확인.)

## 정리(비용)
```bash
terraform destroy
```
RDS `deletion_protection=false`, `skip_final_snapshot=true`(테스트). 운영 전환 시 둘 다 바꾸세요.

## 운영 전환 시 바꿀 것
- HTTPS: ACM 인증서 + ALB 443 리스너 + 도메인(호스트 기반 라우팅) → NEXT_PUBLIC_API_BASE 를 도메인으로.
- RDS Multi-AZ, deletion_protection, final snapshot, 백업.
- web_ingress_cidrs 를 사무실/VPN 으로 제한.
- 원격 tfstate(S3+DynamoDB 잠금).
- 태스크를 프라이빗 서브넷 + NAT 로(공인 IP 제거).
