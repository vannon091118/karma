"""
Agent Runtime Kernel — Event Bus

Lightweight in-process publish/subscribe system.
No network. No external dependencies. No threads by default.

Design principles:
- Synchronous delivery within the same process (predictable, testable)
- Typed events (EventType enum — no magic strings in call sites)
- Correlation IDs for tracing cause-effect chains
- Persistence: events can be written to the SQLite store for audit/replay

Usage:
    bus = get_global_bus()
    bus.subscribe(EventType.NEED_DETECTED, handler)
    bus.publish(Event(EventType.NEED_DETECTED, project="x", payload={"need": ...}))
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


# ─── Event Types ─────────────────────────────────────────────────────────────

class EventType(str, Enum):
    """All kernel event types. Extend here — never use raw strings."""

    # Lifecycle
    KERNEL_STARTED      = "kernel.started"
    KERNEL_STOPPED      = "kernel.stopped"

    # Needs
    NEED_DETECTED       = "need.detected"
    NEED_RESOLVED       = "need.resolved"
    NEED_ESCALATED      = "need.escalated"

    # Tasks / Cascade
    TASK_CREATED        = "task.created"
    TASK_STARTED        = "task.started"
    TASK_COMPLETED      = "task.completed"
    TASK_FAILED         = "task.failed"

    # Learning
    PATTERN_STORED      = "learning.pattern_stored"
    PATTERN_APPLIED     = "learning.pattern_applied"
    REWARD_SCORED       = "learning.reward_scored"
    KNOWLEDGE_DISTILLED = "learning.knowledge_distilled"

    # Falsification
    GATE_PASSED         = "gate.passed"
    GATE_FAILED         = "gate.failed"
    PROBE_RESULT        = "gate.probe_result"

    # Reflection
    REFLECTION_STARTED  = "reflection.started"
    REFLECTION_DONE     = "reflection.done"

    # Skill
    SKILL_LOADED        = "skill.loaded"
    SKILL_EVOLVED       = "skill.evolved"
    SKILL_FAILED        = "skill.failed"

    # Improvement
    IMPROVEMENT_CYCLE   = "improvement.cycle"
    IMPROVEMENT_APPLIED = "improvement.applied"

    # Memory
    FACT_SET            = "memory.fact_set"
    FACT_STALE          = "memory.fact_stale"

    # Generic
    ERROR               = "error"
    WARNING             = "warning"


# ─── Event ───────────────────────────────────────────────────────────────────

@dataclass
class Event:
    """
    An immutable unit of information in the kernel.
    Use correlation_id to link cause-effect chains.
    """
    type: EventType
    project: str = "default"
    payload: Dict[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = ""          # Which module emitted this event

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "project": self.project,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
            "source": self.source,
        }


# ─── Handler Type ─────────────────────────────────────────────────────────────

Handler = Callable[[Event], None]


# ─── Event Bus ───────────────────────────────────────────────────────────────

class EventBus:
    """
    Synchronous in-process event bus.

    - subscribe(event_type, handler): Register a handler for an event type.
    - publish(event): Deliver event synchronously to all registered handlers.
    - publish_to_persistence(event, persistence): Also write to SQLite events table.

    Errors in handlers are caught and stored — they never crash the publisher.
    """

    def __init__(self) -> None:
        self._handlers: Dict[EventType, List[Handler]] = defaultdict(list)
        self._wildcard_handlers: List[Handler] = []
        self._error_log: List[Dict[str, Any]] = []

    def subscribe(self, event_type: EventType, handler: Handler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: Handler) -> None:
        """Register a handler that receives all events."""
        self._wildcard_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: Handler) -> None:
        handlers = self._handlers.get(event_type, [])
        if handler in handlers:
            handlers.remove(handler)

    def publish(self, event: Event) -> int:
        """
        Deliver event to all registered handlers.
        Returns number of handlers called.
        Errors in handlers are logged, never re-raised.
        """
        called = 0
        targets = self._handlers.get(event.type, []) + self._wildcard_handlers
        for handler in targets:
            try:
                handler(event)
                called += 1
            except Exception as e:
                self._error_log.append({
                    "handler": getattr(handler, "__name__", repr(handler)),
                    "event_type": event.type.value,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        return called

    def publish_persisted(self, event: Event, persistence: Any) -> int:
        """Publish event AND write it to the SQLite events table."""
        try:
            persistence.emit_event(
                event_type=event.type.value,
                project=event.project,
                payload=event.to_dict(),
                correlation_id=event.correlation_id,
            )
        except Exception as e:
            self._error_log.append({
                "handler": "persistence",
                "event_type": event.type.value,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
        return self.publish(event)

    def error_log(self) -> List[Dict[str, Any]]:
        return list(self._error_log)

    def handler_count(self, event_type: Optional[EventType] = None) -> int:
        if event_type:
            return len(self._handlers.get(event_type, []))
        return sum(len(v) for v in self._handlers.values()) + len(self._wildcard_handlers)

    def clear_handlers(self, event_type: Optional[EventType] = None) -> None:
        if event_type:
            self._handlers.pop(event_type, None)
        else:
            self._handlers.clear()
            self._wildcard_handlers.clear()


# ─── Global Bus ──────────────────────────────────────────────────────────────

_global_bus: Optional[EventBus] = None


def get_global_bus() -> EventBus:
    """Return the process-global event bus (created on first call)."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def reset_global_bus() -> None:
    """Reset global bus — for testing only."""
    global _global_bus
    _global_bus = None
