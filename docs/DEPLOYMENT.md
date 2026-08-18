# Deploying Humin to AWS

Everything here is a command **you** run against **your own** AWS account - nothing in this repo executes any of it automatically, since standing up
billed infrastructure should always be a deliberate, explicit action.

Prerequisites: an AWS account, the [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
configured (`aws configure`) with an IAM user/role that can create Lambda
functions, ECR repos, IAM roles, and EventBridge rules, and
[Docker](https://docs.docker.com/get-docker/) installed locally.

Pick a region with Bedrock model access - `us-east-1` is the safest default.
Set it once:

```bash
export AWS_REGION=us-east-1
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
```

## 1. Request Bedrock model access (console step - can't be scripted around)

1. Open the [Bedrock console](https://console.aws.amazon.com/bedrock/) in your chosen region.
2. **Model access** → **Manage model access** → request:
   - `us.anthropic.claude-haiku-4-5-20251001-v1:0`
   - `amazon.titan-embed-text-v2:0`
3. Access is usually granted instantly to a few minutes for these models. Don't move on until both show **Access granted**.

## 2. Push the backend image to ECR

```bash
aws ecr create-repository --repository-name humin-backend --region "$AWS_REGION"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# from the REPO ROOT (not backend/) - the Dockerfile needs both backend/ and infra/
docker build -f backend/Dockerfile -t humin-backend .
docker tag humin-backend:latest "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/humin-backend:latest"
docker push "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/humin-backend:latest"
```

## 3. Create the Lambda execution role

```bash
aws iam create-role --role-name humin-lambda-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
  }'

aws iam attach-role-policy --role-name humin-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

aws iam put-role-policy --role-name humin-lambda-role --policy-name humin-bedrock \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:'"$AWS_REGION"'::foundation-model/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "arn:aws:bedrock:'"$AWS_REGION"'::foundation-model/amazon.titan-embed-text-v2:0"
      ]
    }]
  }'
```

## 4. Create the two Lambda functions from the same image

Environment variables here are the same ones in `backend/.env` - set them
directly on the function (encrypted at rest by Lambda) rather than
committing them anywhere. For a more production-grade setup later, move
`COCKROACHDB_URL` into AWS Secrets Manager and reference it instead.

```bash
ROLE_ARN=$(aws iam get-role --role-name humin-lambda-role --query 'Role.Arn' --output text)
IMAGE_URI="$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/humin-backend:latest"
ENV_VARS='Variables={COCKROACHDB_URL=<your-cockroachdb-url>,USE_MOCK_DB=false,USE_MOCK_LLM=false,AWS_REGION='"$AWS_REGION"',CORS_ORIGINS=<your-frontend-url>}'

# --- humin-api: serves the REST API the frontend talks to ---
aws lambda create-function \
  --function-name humin-api \
  --package-type Image \
  --code ImageUri="$IMAGE_URI" \
  --role "$ROLE_ARN" \
  --timeout 30 --memory-size 512 \
  --environment "$ENV_VARS"

# Public HTTPS endpoint - no API Gateway needed for a hackathon demo
aws lambda create-function-url-config \
  --function-name humin-api \
  --auth-type NONE \
  --cors '{"AllowOrigins":["*"],"AllowMethods":["*"],"AllowHeaders":["*"]}'

aws lambda add-permission \
  --function-name humin-api \
  --statement-id public-url \
  --action lambda:InvokeFunctionUrl \
  --principal '*' \
  --function-url-auth-type NONE

# Since Oct 2025, Function URLs need a SECOND, separate statement for
# lambda:InvokeFunction itself - the first statement alone still 403s with
# AccessDeniedException even though it looks complete. Easy to miss; cost us
# real debugging time. See https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html
aws lambda add-permission \
  --function-name humin-api \
  --statement-id public-url-invoke \
  --action lambda:InvokeFunction \
  --principal '*' \
  --invoked-via-function-url

# Note the URL this prints - it's NEXT_PUBLIC_API_BASE for the frontend (append /api)
aws lambda get-function-url-config --function-name humin-api --query FunctionUrl --output text

# --- humin-scheduler: runs one cycle for every active campaign, on a schedule ---
aws lambda create-function \
  --function-name humin-scheduler \
  --package-type Image \
  --code ImageUri="$IMAGE_URI" \
  --image-config '{"Command":["scheduler_handler.run_all_active_campaigns"]}' \
  --role "$ROLE_ARN" \
  --timeout 120 --memory-size 512 \
  --environment "$ENV_VARS"
```

## 5. Put the scheduler on an EventBridge schedule

```bash
aws events put-rule --name humin-agent-loop-schedule --schedule-expression "rate(1 hour)"

aws lambda add-permission \
  --function-name humin-scheduler \
  --statement-id humin-eventbridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn "arn:aws:events:$AWS_REGION:$AWS_ACCOUNT_ID:rule/humin-agent-loop-schedule"

aws events put-targets --rule humin-agent-loop-schedule \
  --targets "Id=1,Arn=arn:aws:lambda:$AWS_REGION:$AWS_ACCOUNT_ID:function:humin-scheduler"
```

Swap `rate(1 hour)` for whatever cadence fits your demo.

## 6. Deploy the frontend

The frontend doesn't need to be on AWS - the hackathon's AWS requirement is
about the agent/backend. **Vercel** is the fastest path for a Next.js app:

```bash
cd frontend
npx vercel --prod
```

Set `NEXT_PUBLIC_API_BASE` in the Vercel project settings to your
`humin-api` Function URL + `/api` (e.g. `https://xxxx.lambda-url.us-east-1.on.aws/api`).
Then go back and update the Lambda's `CORS_ORIGINS` env var to the real
Vercel URL (tighten it from `*`/`AllowOrigins` too, once you know the exact
origin).

If you'd rather keep everything on AWS for a cleaner story, **AWS Amplify
Hosting** is the equivalent one-command deploy for a GitHub-connected Next.js
app - same idea, different button.

## 7. Point the schema at the live cluster (if you haven't already)

```bash
cockroach sql --url "$COCKROACHDB_URL" -f backend/app/db/schema.sql
```

## 8. Verify

```bash
curl https://<your-humin-api-url>/api/health
curl https://<your-humin-api-url>/api/system/status   # confirms live mode, not mock
```

Open the Settings page in the deployed frontend - it should show
`cockroachdb.mode: "live"` and `bedrock.mode: "live"`.

## Checklist mapping (for the Devpost submission)

- ✅ Agentic app using CockroachDB as memory, deployed on AWS - steps 1-5
- ✅ ≥2 CockroachDB tools - Distributed Vector Indexing (schema) + Cloud
  Managed MCP Server (generate a service-account API key for your cluster in
  the CockroachDB Cloud console, then set `COCKROACHDB_CLUSTER_ID`/
  `COCKROACHDB_MCP_API_KEY` in the Lambda env vars - the OAuth flow
  `claude mcp add` uses authenticates a personal CLI session, not this)
- ✅ ≥1 AWS service - Bedrock + Lambda + EventBridge, all live after this guide
- ✅ Published functional demo app - the Vercel/Amplify frontend URL + humin-api Function URL
