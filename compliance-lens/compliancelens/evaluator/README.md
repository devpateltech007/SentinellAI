# compliancelens/evaluator/ — AI evaluation

**Version:** V4 (being built). Stage 1, done: choosing the model, the provider adapters,
the prompt and answer format, and `python audit.py ai-test`. Still to come: documents,
screenshot preparation, the full answer checks, the cache and the audit integration.

**Purpose:** judge evidence that code cannot: screenshots and policy documents. Every AI
verdict has a reason and a confidence; anything unclear becomes NEEDS REVIEW.

## Choosing the model (`.env`)

```
COMPLIANCELENS_AI_MODEL=anthropic/claude-opus-5-5   # <provider>/<model name>
COMPLIANCELENS_AI_API_KEY=...                        # the key of that provider
```

| Provider prefix | Goes through | Key | Address |
| --- | --- | --- | --- |
| `anthropic/` (or a bare `claude-...`) | `anthropic` SDK | needed | api.anthropic.com |
| `openai/` | `openai` SDK | needed | api.openai.com |
| `ollama/`, `lmstudio/` | `openai` SDK | none (runs on this computer, free) | 127.0.0.1 |
| `compatible/` | `openai` SDK | if the service needs one | `COMPLIANCELENS_AI_BASE_URL` |

Then run `python audit.py ai-test` (or `make aitest`): one made-up policy text and one
made-up screenshot, each with a known answer. It prints the model, address, price, tokens,
cost and time, never the key. `--ai-model ollama/<name>` tries another model once.

Models in `models.json` (Claude Opus/Sonnet/Haiku 5.5) come with their price, image limits
and whether they take a temperature. Other models get cautious defaults and a warning;
every value can be set in `.env` (see `.env.example`).

## Files

| File | Job |
| --- | --- |
| `settings.py` | Reads `COMPLIANCELENS_AI_*` into `AISettings`; refuses bad values before a run |
| `models.json` | Known models: price per million tokens (with source and date), image limits |
| `providers/base.py` | The neutral `AIRequest` / `AIReply`, stop reasons and errors |
| `providers/anthropic_api.py` | Claude: structured outputs, effort, refusal fallbacks in audits |
| `providers/openai_compat.py` | OpenAI and every OpenAI-compatible server, local ones too |
| `prompt.py`, `prompts/v1.*` | The frozen v1 prompt and answer schema; evidence first, escaped |
| `answer.py` | Strict JSON answer parsing: exact fields and types, no repairs |
| `smoke.py` | The two checks behind `ai-test` |

## Rules that never change

- The key is passed to the SDK explicitly; the SDK never looks for other credentials.
  It is never printed, logged or saved. An Anthropic key is never sent to another provider.
- SDK retries are off; the evaluator decides about retrying. Every call has a timeout.
- No tools, no browsing: the model only reads the evidence it is given.
- A prompt file is never edited once used (`tests/test_prompt.py` pins v1's hash):
  a change becomes v2.
- The AI cache key will **not** be the screenshot's `raw_sha256`: the raw picture is not
  kept, and the image sent to the model is re-encoded. Stage 3 adds a pixel fingerprint.

**Never commit:** API keys (they live in `.env`).
