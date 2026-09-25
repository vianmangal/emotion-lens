# EmotionLens AWS Deployment

## Prerequisites

- AWS CLI configured (`aws configure`)
- Terraform installed
- GitHub repo secrets set (see below)
- A Route 53 origin hostname (for example `origin.cnn.vian1.tech`) and an
  `ap-south-1` ACM certificate that covers it
- An encrypted S3 bucket for Terraform state and a DynamoDB table with a string
  partition key named `LockID` for state locking

Never commit `.tfstate`, `.tfstate.backup`, `.tfvars`, or secret-bearing backend
configuration. The repository uses a partial S3 backend so each environment can
supply its own bucket and lock table.

## Step 1: Provision infrastructure

```bash
cd infra

terraform init \
  -backend-config="bucket=YOUR_TERRAFORM_STATE_BUCKET" \
  -backend-config="key=emotionlens/production.tfstate" \
  -backend-config="region=ap-south-1" \
  -backend-config="dynamodb_table=YOUR_TERRAFORM_LOCK_TABLE"

# Keep secrets out of shell history and Terraform command arguments.
export TF_VAR_db_username="emotionuser"
export TF_VAR_db_password="$(aws secretsmanager get-secret-value \
  --secret-id emotionlens-rds-master-password \
  --query SecretString \
  --output text)"
export TF_VAR_cloudfront_origin_header_value="$(aws secretsmanager get-secret-value \
  --secret-id emotionlens-cloudfront-origin-header \
  --query SecretString \
  --output text)"

terraform apply \
  -var="aws_region=ap-south-1" \
  -var="acm_certificate_arn=arn:aws:acm:ap-south-1:ACCOUNT_ID:certificate/CERT_ID" \
  -var="backend_origin_domain_name=origin.cnn.vian1.tech" \
  -var="route53_zone_id=YOUR_HOSTED_ZONE_ID"
```

Create `emotionlens-cloudfront-origin-header` once with at least 32 random
characters (for example, `openssl rand -hex 32`) and reuse it for later plans.
The ALB only accepts CloudFront's managed origin-facing IP range, and its HTTPS
listener forwards requests only when this secret header matches.

For an existing deployment, securely recover the last local state from the
pre-cleanup revision and run `terraform init -migrate-state` with the S3 backend
arguments before planning. Do not initialize an empty backend and apply against
existing resources; Terraform would try to create duplicates.

For an existing unencrypted RDS instance, do **not** apply the
`storage_encrypted = true` change as a blind replacement. Snapshot the database,
copy the snapshot with the KMS key, restore an encrypted instance, test it, cut
applications over, and then import the replacement into Terraform state. Review
`terraform plan` before every apply.

Changing an existing ECR repository from AES-256 to KMS encryption also requires
a replacement repository. Copy or rebuild required images and cut ECS over
deliberately rather than allowing an unreviewed replacement.

Useful outputs:

```bash
terraform output cloudfront_domain
terraform output alb_dns_name
terraform output ecr_repository_url
terraform output rds_endpoint
```

## Step 2: Upload the model to S3

```bash
aws s3 cp emotion_model.keras s3://emotionlens-models/emotion_model.keras --region ap-south-1
```

## Step 3: Populate Secrets Manager values

```bash
aws secretsmanager put-secret-value \
  --secret-id emotionlens-database-url \
  --secret-string "postgresql+asyncpg://emotionuser:<ROTATED_PASSWORD>@<rds_endpoint>:5432/emotiondb" \
  --region ap-south-1
```

Pass the real value through a protected environment variable or secure input;
do not leave it in shell history. Rotate the previously committed RDS password
before deploying these changes.

## Step 4: Build and push the initial backend image

```bash
ECR_REPO=$(terraform -chdir=infra output -raw ecr_repository_url)
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin "$ECR_REPO"

docker build -f backend/Dockerfile -t "$ECR_REPO:latest" .
docker push "$ECR_REPO:latest"
```

## Step 5: Configure GitHub Actions secrets

Set these repository secrets:

- `AWS_ROLE_ARN` (GitHub OIDC role for deployments)
- `FRONTEND_BUCKET` (emotionlens-frontend)
- `CLOUDFRONT_DISTRIBUTION_ID` (from CloudFront console)
- `ECS_SUBNETS` (comma-separated public subnet IDs for the recovered deployment)
- `ECS_SECURITY_GROUPS` (comma-separated ECS security group IDs)

`VITE_API_URL` is optional. The recommended production setup is to proxy `/predict` and `/health` through CloudFront on the same site domain.

The recovered deployment currently runs Fargate tasks in the public subnets
with public IPs because its NAT gateways and VPC endpoints were removed. Set
`ECS_SUBNETS` to those public subnet IDs for this environment. The ECS security
group still allows inbound traffic only from the ALB security group. Reconcile
the Terraform state and private-network design before applying the Terraform
configuration again.

Helper commands to fetch subnet and SG IDs:

```bash
aws ec2 describe-subnets \
  --filters "Name=tag:Name,Values=emotionlens-public-*" \
  --query "Subnets[*].SubnetId" \
  --output text

aws ec2 describe-security-groups \
  --filters "Name=tag:Name,Values=emotionlens-ecs-sg" \
  --query "SecurityGroups[*].GroupId" \
  --output text
```

## Step 6: Run the initial DB migration

```bash
aws ecs run-task \
  --cluster emotionlens-cluster \
  --launch-type FARGATE \
  --task-definition emotionlens-backend \
  --network-configuration "awsvpcConfiguration={subnets=[PUBLIC_SUBNET_1,PUBLIC_SUBNET_2],securityGroups=[SG_ID],assignPublicIp=ENABLED}" \
  --overrides '{"containerOverrides":[{"name":"backend","command":["alembic","-c","/app/alembic.ini","upgrade","head"]}]}'
```

## Step 7: Deploy on every push

Push to `main` and GitHub Actions will:

- Build and push the backend image to ECR
- Register a new task definition and redeploy ECS
- Run Alembic migrations
- Build the frontend and sync to S3 + CloudFront invalidation
