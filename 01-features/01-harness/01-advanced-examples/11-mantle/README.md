# Run a harness on the Bedrock Mantle (OpenAI-compatible) endpoint

This example runs an AgentCore harness against the **Mantle** endpoint
(`bedrock-mantle.<region>.api.aws`), the OpenAI-compatible face of Amazon Bedrock. You select it on
the harness with `--api-format responses` (or `chat_completions`) instead of the default
`converse_stream`, which routes inference through `bedrock-mantle` rather than `bedrock-runtime`.

- **[gpt56](gpt56)** — **`openai.gpt-5.6-luna`** with `--api-format responses`.
  Deploy, invoke, and confirm spans in CloudWatch. GPT Marketplace models need
  `aws-marketplace:Subscribe` on the harness execution role; `demo.sh` attaches that after deploy.

For the LiteLLM routing variant of the same Mantle path (a credential provider plus
`--model-provider lite_llm`), see **[../12-litellm-mantle](../12-litellm-mantle)**.

The `gpt56/` folder is self-contained: it has its own `demo.sh`, `cleanup.sh`, `README.md`, and
recording.
