"""符合 OpenTelemetry 规范的分布式链路追踪与 Span 记录器。"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    """单次操作调用链路节点。"""

    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    status: str = "ok"  # "ok", "error"

    @property
    def duration_ms(self) -> float:
        if self.end_time is None:
            return 0.0
        return max(0.0, (self.end_time - self.start_time) * 1000.0)

    def finish(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.status = status


class Tracer:
    """轻量级链路追踪器。"""

    def __init__(self, service_name: str = "orangecode") -> None:
        self.service_name = service_name
        self.completed_spans: list[Span] = []

    @contextmanager
    def start_span(
        self,
        name: str,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[Span]:
        """开启并自动闭合一个 Span 测量周期。"""
        tid = trace_id or uuid.uuid4().hex
        sid = uuid.uuid4().hex[:16]
        span = Span(
            name=name,
            trace_id=tid,
            span_id=sid,
            attributes=attributes or {},
        )
        try:
            yield span
            span.finish(status="ok")
        except Exception as e:
            span.finish(status="error")
            span.attributes["error.type"] = type(e).__name__
            span.attributes["error.message"] = str(e)
            raise
        finally:
            self.completed_spans.append(span)
