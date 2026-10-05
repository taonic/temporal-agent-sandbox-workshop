"""Provider registry. Add a provider by implementing SandboxProvider and listing it here."""

from max_agent.sandbox.models import ProviderConfig
from max_agent.sandbox.providers.base import PermanentProviderError, SandboxProvider


def _daytona():
    from max_agent.sandbox.providers.daytona import DaytonaProvider

    return DaytonaProvider


def _local():
    from max_agent.sandbox.providers.local import LocalProvider

    return LocalProvider


# Lazy imports: a worker only loads the SDKs of the providers it actually uses.
_REGISTRY = {"daytona": _daytona, "local": _local}


def is_registered(provider_type: str) -> bool:
    return provider_type in _REGISTRY


def get_provider(config: ProviderConfig) -> SandboxProvider:
    if config.type not in _REGISTRY:
        raise PermanentProviderError(f"unknown provider {config.type!r}")
    return _REGISTRY[config.type]()(config.options)


__all__ = ["get_provider", "is_registered", "PermanentProviderError", "SandboxProvider"]
