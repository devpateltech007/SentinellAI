# compliancelens/evaluator/ — AI evaluation

**Version:** V4 (empty until then). In V1 to V3 the code check lives in `engine.py`.

**Purpose:** judge evidence that code cannot: screenshots, policy documents and free text.
Every AI verdict has a reason and a confidence.

**What goes here (V4):**
- `ai.py`: send the rule + evidence to the model and parse the JSON reply.
- `prompts/`: versioned prompt text.
- Safety rules: invalid JSON (after one retry), `UNSURE` or low confidence → NEEDS REVIEW;
  an invented quote → NEEDS REVIEW; temperature 0; store model name, prompt version, raw reply.
- Cache AI results by the raw evidence hash so unchanged evidence costs nothing.

**Library added in V4:** the AI SDK you pick (Claude API or Amazon Bedrock via boto3).

**Never commit:** API keys (they live in `.env`).
