"""Independent provider adapters plus the fallback manager."""

from .base import (
    AllProvidersUnavailable,
    NoProviderConfigured,
    ProviderAdapter,
    ProviderError,
    ProviderErrorKind,
    ProviderMessage,
    ProviderRequest,
    ProviderResponse,
    ProviderSwitch,
    ProviderToolCall,
    ProviderUsage,
    ToolDefinition,
)
from .gemini import GeminiAdapter
from .huggingface import HuggingFaceAdapter
from .manager import CompletionResult, ProviderManager

__all__ = [
    "AllProvidersUnavailable",
    "CompletionResult",
    "GeminiAdapter",
    "HuggingFaceAdapter",
    "NoProviderConfigured",
    "ProviderAdapter",
    "ProviderError",
    "ProviderErrorKind",
    "ProviderManager",
    "ProviderMessage",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderSwitch",
    "ProviderToolCall",
    "ProviderUsage",
    "ToolDefinition",
]
