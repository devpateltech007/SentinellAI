"""AI evaluation (V4): judge screenshots and policy documents with any AI model.

    settings.py   which model to use (COMPLIANCELENS_AI_MODEL in .env) and what it can do
    models.json   price and limits of the models we know
    providers/    one adapter per kind of API (Anthropic, OpenAI-compatible)
    prompt.py     the versioned prompt and answer schema (prompts/)
    answer.py     strict reading of the model's JSON answer
    smoke.py      the two small checks behind `python audit.py ai-test`
    ai.py         the judge: one document or screenshot -> AIOutcome (accepted, or why not)
    images.py     screenshots for the AI: the same pixels live or from a saved run, fitted
    budget.py     the call and $ limits per run
    cache.py      accepted answers, reused for the same evidence, rule and model

Check the model in .env with `python audit.py ai-test` before an audit.
"""
