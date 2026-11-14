"""Public surface of the streaming package."""

from .consumer import (
    KafkaEventSource,
    ListEventSource,
    SyntheticEventSource,
    run_stream,
)
from .event_processor import CollectingSink, GraphEventProcessor, ProcessingResult
from .window_manager import WindowManager

__all__ = [
    "CollectingSink",
    "GraphEventProcessor",
    "KafkaEventSource",
    "ListEventSource",
    "ProcessingResult",
    "SyntheticEventSource",
    "WindowManager",
    "run_stream",
]
