"""AI providers: one adapter per kind of API, all behind providers.base.Provider.

To add one: write providers/<name>.py with a `create(settings, http_client)` function
and register its module here. The SDK is imported only when the adapter is created,
so `history`, `verify` and `run --no-ai` never need it.
"""

import importlib

ADAPTERS = {
    "anthropic": "compliancelens.evaluator.providers.anthropic_api",
    "openai_compatible": "compliancelens.evaluator.providers.openai_compat",
}


def get_provider(settings, http_client=None):
    """The adapter for `settings.adapter`. Raises NotInstalled if its SDK is missing.

    `http_client` is for tests (a client with a fake transport); normal runs leave it out.
    """
    module = importlib.import_module(ADAPTERS[settings.adapter])
    return module.create(settings, http_client)
