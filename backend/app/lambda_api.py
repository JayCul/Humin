"""AWS Lambda entry point for the FastAPI app itself, via Mangum.

This is deliberately separate from `infra/lambda/handler.py` (the scheduled
agent-loop entry point) - same container image, two different Lambda
functions at deploy time:

  - `humin-api`       handler = app.lambda_api.handler        (this file)
                       fronted by an API Gateway HTTP API or a Function URL,
                       serves the same REST API the frontend talks to locally.
  - `humin-scheduler`  handler = handler.run_all_active_campaigns
                       (infra/lambda/handler.py), triggered on an EventBridge
                       schedule.

Both ship in the same image; which one a given Lambda *resource* runs is
just its configured handler path. See docs/DEPLOYMENT.md for the exact
`aws lambda create-function` commands for each.
"""
from __future__ import annotations

from mangum import Mangum

from app.main import app

# text_mime_types=[] forces every response through Mangum's base64 path
# (isBase64Encoded=true) instead of returning JSON bodies as a raw text
# string. With the default text_mime_types, a Lambda Function URL mangles
# any non-ASCII character in the body (e.g. an em dash in AI-generated ad
# copy comes back as "â€"" - a UTF-8-decoded-as-Latin-1 round trip) because
# the Function URL invoke path doesn't handle Mangum's non-base64 text
# responses the way API Gateway does. Always base64-encoding sidesteps it.
handler = Mangum(app, text_mime_types=[])
