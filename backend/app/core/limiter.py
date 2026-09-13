"""全局限流器 + 简单熔断（D47 / D39）。

所有 LLM 调用（判定/③分析/诊断/摘要/记忆提炼）与对外工具调用统一途经：
- 信号量：限制并发（LLM_SEMAPHORE）
- 令牌桶：限制速率（LLM_RPM）
- 熔断：连续失败 OPEN → 半开探测 → 恢复
"""
from __future__ import annotations

import time
import threading
from enum import Enum

from app.configs.settings import get_settings
from app.core.logging import logger


class State(str, Enum):
    CLOSED = "closed"      # 正常
    OPEN = "open"          # 熔断打开
    HALF_OPEN = "half_open"


class TokenBucket:
    def __init__(self, rate_per_min: int = 60, burst: int = 5):
        self.rate_per_sec = rate_per_min / 60.0
        self.capacity = burst
        self.tokens = float(burst)
        self.last = time.monotonic()

    def acquire(self, n: int = 1) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate_per_sec)
        self.last = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        open_seconds: float = 15.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.open_seconds = open_seconds
        self.state = State.CLOSED
        self.failures = 0
        self.open_until = 0.0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            if self.state == State.OPEN and time.monotonic() >= self.open_until:
                self.state = State.HALF_OPEN
            return self.state != State.OPEN

    def record_success(self) -> None:
        with self.lock:
            if self.state == State.HALF_OPEN:
                self.state = State.CLOSED
            self.failures = 0

    def record_failure(self) -> None:
        with self.lock:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.state = State.OPEN
                self.open_until = time.monotonic() + self.open_seconds
                logger.warning(f"熔断 {self.name} 打开 {self.open_seconds}s")


class GlobalLimiter:
    def __init__(self) -> None:
        s = get_settings()
        self.semaphore = threading.Semaphore(s.llm_semaphore)
        self.bucket = TokenBucket(s.llm_rpm, burst=s.llm_semaphore)
        self.llm_breaker = CircuitBreaker("llm")
        self.tool_breaker = CircuitBreaker("tool")
        self.kb_breaker = CircuitBreaker("kb")

    def try_acquire_llm(self) -> bool:
        if not self.llm_breaker.allow():
            return False
        if not self.semaphore.acquire(blocking=True):
            return False
        return self.bucket.acquire(1)

    def release_llm(self) -> None:
        self.semaphore.release()

    def llm_success(self) -> None:
        self.llm_breaker.record_success()

    def llm_failure(self) -> None:
        self.llm_breaker.record_failure()


limiter = GlobalLimiter()