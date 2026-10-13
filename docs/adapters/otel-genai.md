# OpenTelemetry GenAI conventions: what was checked

Checked **2026-10-14** (T-850). The GenAI semantic conventions have moved from the main
OpenTelemetry semconv site to `open-telemetry/semantic-conventions-genai`
(`docs/gen-ai/gen-ai-spans.md`, `gen-ai-agent-spans.md`). Status of the agent and tool span
conventions and of every attribute below: **Development** (not stable). The repository had no
tagged release at the time of checking, so there is nothing to pin yet.

Names used by `arg.adapters.otel_genai` (read from those files):

| Convention | Value |
|---|---|
| `gen_ai.operation.name` well-known values | `execute_tool`, `invoke_agent`, `create_agent`, `chat`, `generate_content`, `text_completion`, `embeddings`, `retrieval` |
| Tool span attributes | `gen_ai.tool.name` (required), `gen_ai.tool.call.id`, `gen_ai.tool.type` |
| Agent span attributes | `gen_ai.agent.name`, `gen_ai.agent.id` |
| Model attribute | `gen_ai.request.model` |
| Span name | `execute_tool {gen_ai.tool.name}`, `invoke_agent {gen_ai.agent.name}` |

Mapping to envelope trace steps: `execute_tool` → `tool_call`; `retrieval`, `embeddings` →
`retrieval`; `chat`, `generate_content`, `text_completion` → `model_call`;
`invoke_agent`/`create_agent` → no step (they describe the agent, not something it did).
Check steps (`kind: check`) have no GenAI equivalent and are recorded by the adapter directly.

Because the status is Development, re-verify these names before upgrading anything that emits
them; the mapping is isolated in one small module for that reason.
