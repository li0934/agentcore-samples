# Run a harness on the Bedrock Mantle (OpenAI-compatible) endpoint

This example runs an AgentCore harness against the **Mantle** endpoint
(`bedrock-mantle.<region>.api.aws`), the OpenAI-compatible face of Amazon Bedrock. You select it on
the harness with `--api-format responses` (or `chat_completions`) instead of the default
`converse_stream`, which routes inference through `bedrock-mantle` rather than `bedrock-runtime`.

- **[gpt56](gpt56)** — **`openai.gpt-5.6-luna`** with `--api-format responses`.
  Deploy, invoke, and confirm spans in CloudWatch. GPT Marketplace models need
  `aws-marketplace:Subscribe` on the harness execution role; `demo.sh` attaches that after deploy.

The `gpt56/` folder is self-contained: it has its own `demo.sh`, `cleanup.sh`, `README.md`, and
recording.

## Note on LiteLLM (`lite_llm`)

A former companion sample routed the same Mantle path through `--model-provider lite_llm`
plus an API-key credential. That walkthrough was **removed as unnecessary** for this
tutorial set: Mantle is already covered by `bedrock` + `--api-format responses` in
`gpt56`, and the usual providers (`bedrock`, `open_ai`, `gemini`) cover common cases
without a LiteLLM hop. See [../12-litellm-mantle](../12-litellm-mantle) for the short
rationale.
