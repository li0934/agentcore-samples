# Run GPT-5.6 Luna on a harness via the Mantle (OpenAI Responses) endpoint

![Agent Inspector span tree for the Mantle harness](images/02-agent-inspector.gif)

| Information         | Details                                                          |
|:--------------------|:-----------------------------------------------------------------|
| Tutorial type       | Advanced example                                                 |
| Agent type          | General-purpose assistant                                        |
| Agentic framework   | None (AgentCore CLI)                                             |
| LLM model           | OpenAI `gpt-5.6-luna`, served through Amazon Bedrock Mantle |
| Tutorial components | AgentCore harness, Bedrock Mantle endpoint, Observability, CloudWatch |
| Example complexity  | Beginner                                                         |
| Tooling             | `agentcore` CLI (no application code)                            |

A Bedrock harness can call its model two ways, chosen by one config field, `apiFormat`. This
example uses the OpenAI-compatible **Mantle** path to run OpenAI's `gpt-5.6-luna`
through Amazon Bedrock — no API key, the harness execution role's Bedrock permissions are used.

## What you learn

- The difference between the `bedrock-runtime` (Converse) and `bedrock-mantle` (OpenAI-compatible) endpoints
- How to select the endpoint with `agentcore add harness --api-format`
- Run OpenAI GPT-5.6 Luna on a harness with no API key
- Confirm the Mantle harness is observable — the GenAI span tree lands in `aws/spans`
- The model-id difference between Mantle and `bedrock-runtime` OpenAI paths

## Two endpoints, one flag

A `bedrock` harness routes inference based on `--api-format`:

| `--api-format` | Endpoint | API | Use when |
|---|---|---|---|
| `converse_stream` (default) | `bedrock-runtime` | Bedrock Converse | Bedrock-native models and tools |
| `responses` | `bedrock-mantle` | OpenAI Responses | OpenAI-compatible, stateful, server-side tools |
| `chat_completions` | `bedrock-mantle` | OpenAI Chat Completions | Bringing OpenAI SDK-style code to Bedrock |

`responses` and `chat_completions` are the OpenAI-compatible "Mantle" APIs. With them, a `bedrock`
provider harness sends inference to the `bedrock-mantle.{region}.api.aws` endpoint. The choice is
saved to `harness.json` as `model.apiFormat`; it is not a different provider (the provider stays
`bedrock`).

## ⚠️ Mantle vs runtime model ids

GPT-5.6 models are invoked with different ids depending on the endpoint:

| Endpoint | Model id |
|---|---|
| **`bedrock-mantle`** (this example) | **`openai.gpt-5.6-luna`** (foundation model id) |
| `bedrock-runtime` OpenAI Responses path | `us.openai.gpt-5.6-luna` (cross-Region inference profile) |

Use the foundation model id with `--api-format responses` / `chat_completions` on Mantle.

## Architecture

```
agentcore CLI  → create --no-agent → add harness --api-format responses → deploy
                                                   │
                                                   ▼
[Harness] READY ──invoke──▶ [Firecracker microVM]
                               ├── agent loop (gpt-oss-120b)
                               └── service-side ADOT instrumentation
                                          │  OpenTelemetry spans
                                          ▼   (model inference → bedrock-mantle endpoint)
                          CloudWatch  ──  aws/spans  (Transaction Search)
```

The harness is auto-instrumented exactly like a Converse harness — no ADOT, no `OTEL_*` variables.

## Prerequisites

- **AgentCore CLI (preview):** `npm install -g @aws/agentcore@preview` (preview.13+ — that is when
  `--api-format` shipped in the CLI).
- **AWS CLI v2** with credentials for a harness preview region
  (`us-east-1`, `us-west-2`, `ap-southeast-2`, `eu-central-1`).
- Amazon Bedrock access to `openai.gpt-5.6-luna` in that region (e.g. `us-east-1`, `us-east-2`, `us-west-2`).
- **CloudWatch Transaction Search enabled once per account** (the script checks and prints the
  enable commands if missing). See
  [AgentCore Observability — getting started](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html).

## Run

```bash
# default region us-east-1; override with AWS_REGION
./demo.sh

# offline self-test (no AWS calls)
./demo.sh --self-test
```

`demo.sh` runs these steps, printing each command:

1. Pre-flight checks (CLI, credentials, Transaction Search).
2. Scaffold an empty project and add a harness with `--api-format responses` (gpt-5.6-luna, memory on).
3. Deploy — CDK creates the IAM execution role and the harness is created.
4. Invoke the harness through Mantle across one session.
5. Query `aws/spans` to confirm OpenTelemetry spans were emitted.
6. Launch the **Agent Inspector** (`agentcore dev --skip-deploy`) to watch the telemetry live.

The scaffold step, showing `--api-format responses` and the `apiFormat` written into `harness.json`:

![demo.sh adding a harness with --api-format responses](images/01-deploy.gif)

> **Account safety:** the account ID is detected at runtime (used only for a git-ignored
> `aws-targets.json`) and masked as `<ACCOUNT>`; your username/home path is masked as `<USER>`. A
> terminal recording of `demo.sh` is safe to share.

## The single config difference

Everything is the same as a default harness except the model block. After `add harness`,
`harness.json` reads:

```json
"model": {
  "provider": "bedrock",
  "modelId": "openai.gpt-5.6-luna",
  "apiFormat": "responses"
}
```

The equivalent CLI call:

```bash
agentcore add harness --name my-mantle-agent \
  --model-provider bedrock \
  --model-id openai.gpt-5.6-luna \
  --api-format responses \
  --system-prompt "You are a helpful assistant."
```

## View the results

In the Agent Inspector (or the CloudWatch GenAI Observability console), open a trace to see the
span tree — same shape as any harness, and the span carries the Mantle model id and token usage:

```
POST /invocations
  └─ invoke_agent Strands Agents          ... in / ... out
       └─ execute_event_loop_cycle
            └─ chat                         gen_ai.request.model = openai.gpt-5.6-luna
```

```
https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#gen-ai-observability
```

> Spans take **3-10 minutes** to appear (the infrastructure spans land first; the `chat` /
> `invoke_agent` spans follow). Don't conclude "no telemetry" early — leave the Inspector open.

## Best practices

- **Use the Mantle foundation model id** (`openai.gpt-5.6-luna`), not the `us.` inference profile.
- **`--api-format` is set at add-harness time.** `agentcore invoke` overrides `--model-id` and
  `--model-provider` but not the API format. To switch Converse↔Mantle per call, use the boto3
  `invoke_harness` `model` object.
- **No API key needed** for a `bedrock` Mantle harness — it uses the execution role's Bedrock
  permissions, just like a Converse harness.
- **Marketplace models** (GPT-5.6 etc.) need `aws-marketplace:Subscribe` on the harness
  execution role. `demo.sh` attaches that policy after deploy (CDK does not yet).
- **Enable Transaction Search once per account, early**, so spans are visible when you need them.
- **Clean up.** Run `./cleanup.sh` when you are done so no billable resources are left.

## Clean up

```bash
./cleanup.sh
```

Removes the harness and memory, deletes the CDK stack, and removes the local workspace.

## Where to next

- **[10-getting-started-with-agent-inspector](../../10-getting-started-with-agent-inspector)** — the default (Converse) harness + Agent Inspector walkthrough this builds on.
- **[Endpoints supported by Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html)** — `bedrock-runtime` vs `bedrock-mantle`.
- **[AgentCore harness dev guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/harness.html)** — the full harness reference.
