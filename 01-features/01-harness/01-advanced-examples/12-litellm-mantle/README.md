# LiteLLM → Mantle sample — intentionally omitted

This directory no longer ships a runnable demo. A previous sample routed an
AgentCore harness through `--model-provider lite_llm` to the Bedrock Mantle
endpoint (same destination as [11-mantle/gpt56](../11-mantle/gpt56)).

## Why it is not needed here

Harness already has first-class model providers for the common cases:

| Provider | Typical use |
|---|---|
| `bedrock` | Bedrock / Mantle via the execution role (see [11-mantle/gpt56](../11-mantle/gpt56)) |
| `open_ai` | OpenAI direct |
| `gemini` | Gemini direct |

`lite_llm` is a routing layer (base URL + API key), not a distinct hosted model.
The old sample only showed reaching Mantle through that extra hop plus a
credential provider. For learning Mantle, **`bedrock` + `--api-format responses`
in [11-mantle/gpt56](../11-mantle/gpt56) is enough**.

In practice:

- Teams that use Azure usually call Azure with a dedicated integration, not via a
  Mantle LiteLLM detour in this sample set.
- Self-hosted org model endpoints and multi-provider fallback via LiteLLM are
  uncommon relative to the first-class providers above.

The Harness CLI still supports `lite_llm` when you need a custom OpenAI-compatible
gateway; this repo simply does not maintain a Mantle-via-LiteLLM walkthrough.
