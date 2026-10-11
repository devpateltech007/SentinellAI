# compliancelens/evaluator/ — AI evaluation

**Version:** V4 (being built). Stage 1, done: choosing the model, the provider adapters,
the prompt and answer format, and `python audit.py ai-test`. Stage 2, done: documents are
read by `connectors/files.py` and saved with the run; the database has the AI tables.
Stage 3, done: the judge (`ai.py`), screenshot preparation, the budget and the cache.
Still to come: connecting it to `python audit.py run` (Stage 4).

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
| `ai.py` | The judge: asks about one document or screenshot, retries once, decides what the answer is worth (`AIOutcome`), compares a cross-check |
| `images.py` | Screenshots for the AI: the page's pixels (live, or from a saved PNG without its banner), `pixel_sha256`, fitted to the model's limits |
| `budget.py` | The call and $ limits per run: worst case reserved before each call, real tokens charged after |
| `cache.py` | Accepted answers in `compliance.db` (`ai_cache`), reused for the same evidence, rule, model and prompt |

## How an answer is judged (`ai.py`)

The first row that applies decides. Only `accepted` gives PASS or FAIL; everything else
is NEEDS REVIEW with the reason, so an unclear answer can never become PASS.

| Situation | Status |
| --- | --- |
| The document wasn't read, or no screenshot was taken | `evidence_missing` (no call) |
| The screenshot would shrink below 75% to fit the model | `image_too_big` (no call) |
| `--no-ai`, no key, budget used up, SDK missing | `disabled`, `not_configured`, `budget_exhausted`, `not_installed` (no call) |
| Timeout, connection, 429, 5xx (tried once more) | `provider_error` |
| Bad key, unknown model, bad request, no credit | `provider_error` |
| The model refused, or a content filter stopped it | `refusal` |
| The answer was cut off | `truncated` |
| Not exactly the answer's JSON, or a field too short/long (tried once more) | `invalid_reply` |
| UNSURE | `unsure` |
| Low confidence | `low_confidence` |
| A document that never states the requirement, `missing_means: fail`, FAIL with no evidence and no quote, high confidence | `accepted` → FAIL |
| PASS or FAIL, but no evidence of the setting found | `inconsistent` |
| A document's PASS or FAIL whose quote isn't in the text | `quote_not_found` |
| A screenshot's PASS or FAIL with no quote | `inconsistent` |
| Otherwise | `accepted` (high or medium confidence kept) |

There is one retry per evaluation, shared by the two "tried once more" rows. Quotes
are matched after normalizing entities, ligatures, typographic quotes and dashes,
broken words and spaces, and must be at least 8 characters. Every attempt (what was
sent, the whole reply, tokens, cost, time) goes into the record for `<ID>.ai.json`;
pictures are recorded by hash, never as pixels.

**Screenshots** are shrunk (never enlarged) to the model's long edge, visual tokens or
pixel count, then sent as a PNG without metadata, so the same page gives the same
`ai_input_sha256`. Models not in `models.json` get 1568 px / 1.2 MP, which a 1440 px
wide full-page capture can't meet at 75%: raise `COMPLIANCELENS_AI_IMAGE_MAX_PIXELS` if
the model reads larger pictures.

**Budget:** before each call the worst case is reserved (input estimated, plus a full
`MAX_TOKENS` answer); a call over `MAX_CALLS_PER_RUN` or `MAX_COST_PER_RUN_USD` isn't
made. With an unknown price only the call limit applies and the cost is recorded as unknown.

**Cache:** only `accepted` answers are kept. A hit costs nothing (0 calls, $0) and
records where the answer came from. The key covers the evidence (document hash and
extractor, or the screenshot's pixels and the picture sent), the rule's wording, the
model settings and the prompt, schema, preparation and validation versions.

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
