# Lambda container image for the Humin backend. Serves BOTH Lambda
# functions described in docs/DEPLOYMENT.md from one image - which handler
# runs is just a per-function config choice (--image-config Command=...),
# not a different build.
#
# Build from the REPO ROOT (not backend/), since it needs both backend/ and
# infra/lambda/ in its context:
#   docker build -f backend/Dockerfile -t humin-backend .

FROM public.ecr.aws/lambda/python:3.12

COPY backend/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY backend/app ${LAMBDA_TASK_ROOT}/app
COPY infra/lambda/handler.py ${LAMBDA_TASK_ROOT}/scheduler_handler.py

# Default - the `humin-api` function uses this as-is; the `humin-scheduler`
# function overrides it to scheduler_handler.run_all_active_campaigns at
# creation time (see docs/DEPLOYMENT.md).
CMD ["app.lambda_api.handler"]
