# infra

**→ For the full deployment path (backend API + scheduler + both AWS
services), see [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md).** It deploys
`backend/Dockerfile` as a single container image to two Lambda functions:
`humin-api` (serves the REST API via a Function URL - `app/lambda_api.py`,
Mangum-wrapped) and `humin-scheduler` (runs the agent loop on an EventBridge
schedule - `lambda/handler.py`, below).

`lambda/handler.py` - the scheduler entry point specifically: runs one
agent cycle for every active campaign. Two scheduling paths exist and they
call the exact same `orchestrator.run_all_active_campaigns()` function, so
behaviour is identical either way:

- **`humin-scheduler` Lambda on EventBridge (production)** - nothing needs
  the dashboard open; this is what you'd actually run. Deployed via
  `docs/DEPLOYMENT.md`.
- **`backend/app/scheduler.py` (live demo)** - an in-process APScheduler
  loop toggled from the dashboard ("Enable autonomous mode"), so the loop's
  autonomy is demonstrable without a deployed AWS stack in front of judges.

## Alternative: zip-based packaging (no Docker)

The container path in `docs/DEPLOYMENT.md` is recommended - it sidesteps
Lambda-runtime binary-compatibility issues with C-extension dependencies
(`psycopg2-binary`, etc.). If you'd rather not use Docker, a plain zip
deploy for the scheduler function alone still works:

```bash
cd backend
pip install -r requirements.txt -t build/
cp -r app build/
cp ../infra/lambda/handler.py build/
cd build && zip -r ../humin-lambda.zip . && cd ..

aws lambda create-function \
  --function-name humin-scheduler \
  --runtime python3.12 \
  --handler handler.run_all_active_campaigns \
  --zip-file fileb://humin-lambda.zip \
  --role arn:aws:iam::<ACCOUNT_ID>:role/<EXECUTION_ROLE> \
  --timeout 120 \
  --environment "Variables={COCKROACHDB_URL=<url>,AWS_REGION=us-east-1,USE_MOCK_LLM=false,USE_MOCK_DB=false}"
```

Then the EventBridge rule steps in `docs/DEPLOYMENT.md` § 5 apply the same
way, just targeting this function's ARN instead.
