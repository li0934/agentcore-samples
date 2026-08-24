"""
AgentCore Harness with JWT Inbound Auth & OAuth-Protected Gateway.

Demonstrates two Harness security primitives:

  Inbound auth (CUSTOM_JWT) — require callers to present a valid JWT before
  the Harness accepts the request. Uses a Cognito user pool (any OIDC provider works).

  Outbound auth (outboundAuth.oauth) — the Harness automatically fetches an
  OAuth token (client credentials grant) to authenticate to an AgentCore Gateway.
  The credential provider is registered once; the Harness handles token exchange
  on every tool call. No secrets in the invoke request.

Architecture:

  User → [User Pool JWT] → Harness → validates JWT (inbound auth)
                                   → fetches M2M token (outbound auth)
                                   → calls Gateway with M2M token
                                   → Gateway validates M2M token
                                   → invokes Lambda tool
                                   → response flows back to user

Usage:
    python oauth_gateway.py

    # Optional: override the Cognito test user credentials
    export HARNESS_USER_NAME="testuser"
    export HARNESS_USER_PASS="TestPassword123!"

    # Skip cleanup to inspect resources
    python oauth_gateway.py --skip-cleanup

Prerequisites:
    - AWS CLI configured with credentials
    - pip install -r ../../requirements.txt
    - AWS_DEFAULT_REGION environment variable set
    - Optional: HARNESS_USER_NAME / HARNESS_USER_PASS (defaults: testuser / TestPassword123!)
"""

import argparse
import os
import sys
import urllib.parse
import uuid
from pathlib import Path

import boto3
import botocore.exceptions
import requests as http_requests

# Local `utils/` (setup_helpers) shadows the shared package at 01-harness/utils/.
# Put the *shared utils directory* on path so its modules import as top-level
# names (`harness`, not `utils.harness`) and do not collide.
_SAMPLE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SAMPLE_DIR.parent.parent / "utils"))

from harness import poll_harness_status
from utils.setup_helpers import (
    cleanup_all,
    create_credential_provider,
    create_gateway_with_lambda_target,
    create_harness_execution_role,
    create_m2m_pool,
    create_user_auth_pool,
    deploy_lambda,
    invoke_harness_event_stream,
    iter_paginated,
)

# ── CLI ────────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser(description="Harness JWT inbound + OAuth outbound demo")
parser.add_argument("--skip-cleanup", action="store_true", help="Keep all resources after the demo")
args = parser.parse_args()

# ── Configuration ─────────────────────────────────────────────────────────────
REGION = boto3.Session().region_name or "us-east-1"
ACCOUNT_ID = boto3.client("sts", region_name=REGION).get_caller_identity()["Account"]
PREFIX = "harness-oauth-demo"

# Credentials for the test Cognito user (override via env if desired)
USER1_NAME = os.environ.get("HARNESS_USER_NAME", "testuser")
USER1_PASS = os.environ.get("HARNESS_USER_PASS", "TestPassword123!")

ac_control = boto3.client("bedrock-agentcore-control", region_name=REGION)
cognito = boto3.client("cognito-idp", region_name=REGION)

print(f"Region: {REGION}  Account: {ACCOUNT_ID}")

# Bound before the outer try so `finally` and the harness try/except cannot leave
# names possibly-unbound for the type checker (or for --skip-cleanup prints).
gw = None
HARNESS_ID = None
HARNESS_ARN = None

# Every step below is wrapped in a single try/finally so a failure part-way
# through still tears down what was already created. Without it, an error
# anywhere between Step 1a and Step 4 left two Cognito pools, a credential
# provider, a Lambda, a gateway + target, a harness and three IAM roles alive —
# all billable, and all blocking the next run with ConflictException.
# cleanup_all discovers resources by name, so it copes with a partial set.
try:
    # ── Step 1: Provision Infrastructure ─────────────────────────────────────
    print("\n=== Step 1a: Cognito User Auth Pool ===")
    pool1 = create_user_auth_pool(REGION, PREFIX, USER1_NAME, USER1_PASS)
    print(f"Discovery URL: {pool1['discovery_url']}")

    print("\n=== Step 1b: Cognito M2M Pool ===")
    pool2 = create_m2m_pool(REGION, PREFIX)
    print(f"Scope: {pool2['scope']}")
    print(f"Discovery URL: {pool2['discovery_url']}")

    print("\n=== Step 1c: OAuth2 Credential Provider ===")
    cred = create_credential_provider(
        REGION,
        PREFIX,
        discovery_url=pool2["discovery_url"],
        client_id=pool2["client_id"],
        client_secret=pool2["client_secret"],
    )

    print("\n=== Step 1d: Lambda Function ===")
    lam = deploy_lambda(REGION, PREFIX)

    print("\n=== Step 1e: Gateway + Lambda Target ===")
    gw = create_gateway_with_lambda_target(
        REGION,
        PREFIX,
        ACCOUNT_ID,
        discovery_url=pool2["discovery_url"],
        allowed_client=pool2["client_id"],
        allowed_scope=pool2["scope"],
        lambda_arn=lam["function_arn"],
        lambda_function_name=lam["function_name"],
    )
    print(f"Gateway ARN: {gw['gateway_arn']}")

    print("\n=== Step 1f: Harness Execution Role ===")
    harness_role = create_harness_execution_role(REGION, PREFIX, ACCOUNT_ID)

    # ── Step 2: Create Harness with CUSTOM_JWT Inbound Auth ──────────────────
    print("\n=== Step 2: Create Harness with CUSTOM_JWT Inbound Auth ===")
    HARNESS_NAME = f"{PREFIX}-harness".replace("-", "_")

    try:
        harness_resp = ac_control.create_harness(
            harnessName=HARNESS_NAME,
            executionRoleArn=harness_role["role_arn"],
            authorizerConfiguration={
                "customJWTAuthorizer": {
                    "discoveryUrl": pool1["discovery_url"],
                    "allowedClients": [pool1["client_id"]],
                }
            },
            model={"bedrockModelConfig": {"modelId": "us.anthropic.claude-haiku-4-5-20251001-v1:0"}},
            systemPrompt=[
                {
                    "text": (
                        "You are an order management assistant. "
                        "Use the gateway tools to look up and update orders. "
                        "Always confirm the order details before making changes."
                    )
                }
            ],
            tools=[
                {
                    "type": "agentcore_gateway",
                    "name": "order-gateway",
                    "config": {
                        "agentCoreGateway": {
                            "gatewayArn": gw["gateway_arn"],
                            "outboundAuth": {
                                "oauth": {
                                    "providerArn": cred["arn"],
                                    "scopes": [pool2["scope"]],
                                    "grantType": "CLIENT_CREDENTIALS",
                                }
                            },
                        }
                    },
                }
            ],
        )
        HARNESS_ID = harness_resp["harness"]["harnessId"]
        HARNESS_ARN = harness_resp["harness"]["arn"]
        print(f"Harness created: {HARNESS_ID}")
    except ac_control.exceptions.ConflictException:
        # ListHarnesses is paginated. Reading only the first page meant that once
        # the account held more harnesses than fit in one page, this recovery path
        # raised "conflict but not found" for a harness that demonstrably exists —
        # the create had just been rejected because of it.
        match = next(
            (
                h
                for h in iter_paginated(ac_control, "list_harnesses", "harnesses")
                if h.get("harnessName") == HARNESS_NAME
            ),
            None,
        )
        if not match:
            raise RuntimeError(f"Harness {HARNESS_NAME} conflict but not found")
        HARNESS_ID = match["harnessId"]
        HARNESS_ARN = match["arn"]
        print(f"Harness already exists: {HARNESS_ID}")

    if HARNESS_ID is None or HARNESS_ARN is None:
        raise RuntimeError(f"Harness {HARNESS_NAME} was not resolved")

    print(f"Harness ID:  {HARNESS_ID}")
    print(f"Harness ARN: {HARNESS_ARN}")

    # A harness takes ~150s to reach READY; poll_harness_status raises on
    # CREATE_FAILED / timeout instead of continuing into a broken invoke.
    print("Waiting for harness READY...")
    poll_harness_status(ac_control, HARNESS_ID)

    # ── Step 3: Get Bearer Token from User Auth Pool ──────────────────────────
    print("\n=== Step 3: Authenticate User — Get Bearer Token ===")
    auth_result = cognito.initiate_auth(
        ClientId=pool1["client_id"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": USER1_NAME, "PASSWORD": USER1_PASS},
    )
    BEARER_TOKEN = auth_result["AuthenticationResult"]["AccessToken"]
    print(f"Got bearer token (first 20 chars): {BEARER_TOKEN[:20]}...")

    # ── Step 4: Invoke Harness with Bearer Token ─────────────────────────────
    print("\n=== Step 4: Invoke Harness with Bearer Token ===")
    escaped_arn = urllib.parse.quote(HARNESS_ARN, safe="")
    url = f"https://bedrock-agentcore.{REGION}.amazonaws.com/harnesses/invoke?harnessArn={escaped_arn}"
    SESSION_ID = f"demo-session-{uuid.uuid4().hex}"

    headers = {
        "Authorization": f"Bearer {BEARER_TOKEN}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": SESSION_ID,
    }
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": "Look up order ORD-001 and tell me its status."}],
            }
        ]
    }

    print(f"Session:  {SESSION_ID}")
    print(f"Endpoint: {url[:80]}...")
    print()

    resp = http_requests.post(url, headers=headers, json=payload, timeout=120, stream=True)
    print(f"HTTP Status: {resp.status_code}")

    if resp.status_code != 200:
        raise RuntimeError(f"InvokeHarness returned HTTP {resp.status_code}: {resp.text[:1000]}")

    full_text = []
    stream_errors = []
    raw = resp.content
    # boto3 cannot attach the JWT Authorization header, but the body is still the
    # InvokeHarness event stream — decode it with botocore like response["stream"].
    # exception: true frames (runtimeClientError, …) raise EventStreamError instead
    # of yielding a dict; HTTP status stays 200, so catching here is what keeps a
    # mid-agent failure from looking like an empty success.
    try:
        for event in invoke_harness_event_stream(raw, REGION):
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {})
                if "text" in delta:
                    full_text.append(delta["text"])
                    print(delta["text"], end="", flush=True)
            elif "messageStop" in event:
                print()
    except (botocore.exceptions.ClientError, botocore.exceptions.BotoCoreError) as e:
        stream_errors.append(str(e))
        print(f"\n❌ Stream error: {type(e).__name__}: {e}")

    if stream_errors:
        raise RuntimeError(f"InvokeHarness streamed {len(stream_errors)} error frame(s); first: {stream_errors[0]}")

    if not full_text:
        print(f"\nRaw first 500 bytes: {raw[:500]!r}")
        raise RuntimeError("InvokeHarness returned no text deltas and no error frame — nothing was generated.")

    print(f"\n--- Full response ({len(''.join(full_text))} chars) ---")
    print("".join(full_text))

    # Only reached when the invoke actually produced output, so the summary
    # describes what happened rather than what was supposed to happen.
    print("\n=== What just happened? ===")
    print("1. You sent a User Auth Pool JWT → harness validated it (inbound auth)")
    print("2. Agent decided to call get_order → harness fetched an M2M token from M2M Pool")
    print("3. Harness called the Gateway with the M2M token (outbound auth)")
    print("4. Gateway validated it, invoked Lambda, order details flowed back")
    print("Three auth mechanisms, zero secrets in the invoke call.")

finally:
    # ── Step 5: Cleanup ───────────────────────────────────────────────────────
    # In `finally`, so a failure in any step above still releases the two Cognito
    # pools, the credential provider, the Lambda, the gateway and the harness
    # instead of leaving them running and billing.
    if not args.skip_cleanup:
        print("\n=== Step 5: Cleanup ===")
        cleanup_all(REGION, PREFIX)
    else:
        print("\n=== Skipping cleanup (--skip-cleanup) ===")
        if HARNESS_ID is not None:
            print(f"Harness ID:  {HARNESS_ID}")
        if gw is not None:
            print(f"Gateway ARN: {gw['gateway_arn']}")
        print("Run 'python oauth_gateway.py' again to reuse existing resources.")
