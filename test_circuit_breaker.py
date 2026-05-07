"""
test_circuit_breaker.py
-----------------------
Automated test suite for the Circuit Breaker pattern.
 
Tests:
  1. Unit tests  – test the CircuitBreaker class in isolation (no HTTP)
  2. Integration – test the FastAPI endpoints via HTTPX async client
 
Run with:
    pytest test_circuit_breaker.py -v
 
Or run the standalone demo (no pytest needed):
    python test_circuit_breaker.py
"""
 
import asyncio
import time
import pytest
import pytest_asyncio
import httpx
from fastapi.testclient import TestClient
 
# ---- import our own modules ----
from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError, CircuitState
from studysync import app, llm_circuit, LLM_SHOULD_FAIL
 
 
# =========================================================================== #
#  PART A – Unit Tests (CircuitBreaker class, no HTTP)                         #
# =========================================================================== #
 
class TestCircuitBreakerUnit:
 
    def setup_method(self):
        """Fresh circuit breaker before each test."""
        self.cb = CircuitBreaker(
            name="test",
            failure_threshold=3,
            recovery_timeout=2.0,   # short for fast tests
            call_timeout=1.0,
        )
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_starts_closed(self):
        """Circuit must begin in CLOSED state."""
        assert self.cb.state == CircuitState.CLOSED
        print("\n✅ [UNIT] Circuit starts CLOSED")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_successful_call_stays_closed(self):
        """A passing call keeps the circuit CLOSED."""
        async def good():
            return "ok"
 
        result = await self.cb.call(good)
        assert result == "ok"
        assert self.cb.state == CircuitState.CLOSED
        print("✅ [UNIT] Successful call keeps circuit CLOSED")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self):
        """
        After `failure_threshold` consecutive failures, the circuit must OPEN.
        This is the core protection mechanism.
        """
        async def bad():
            raise RuntimeError("LLM is down")
 
        for i in range(self.cb.failure_threshold):
            with pytest.raises(RuntimeError):
                await self.cb.call(bad)
 
        assert self.cb.state == CircuitState.OPEN
        print(f"✅ [UNIT] Circuit OPENED after {self.cb.failure_threshold} failures")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_open_circuit_blocks_immediately(self):
        """
        Once OPEN, calls are rejected INSTANTLY without touching the upstream.
        This prevents the server from hanging.
        """
        async def bad():
            raise RuntimeError("LLM is down")
 
        # Trip the circuit
        for _ in range(self.cb.failure_threshold):
            with pytest.raises(RuntimeError):
                await self.cb.call(bad)
 
        assert self.cb.state == CircuitState.OPEN
 
        # Now prove the next call is blocked instantly (no timeout wait)
        start = time.monotonic()
        with pytest.raises(CircuitBreakerOpenError):
            await self.cb.call(bad)
        elapsed = time.monotonic() - start
 
        assert elapsed < 0.5, f"Open circuit should block instantly, took {elapsed:.2f}s"
        print(f"✅ [UNIT] Open circuit blocked in {elapsed:.4f}s (no upstream hit)")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_timeout_counts_as_failure(self):
        """
        A call that exceeds `call_timeout` must count as a failure.
        This is what stops the 60-second LLM hang from blocking the server.
        """
        async def slow():
            await asyncio.sleep(10)   # much longer than call_timeout=1.0
 
        with pytest.raises(asyncio.TimeoutError):
            await self.cb.call(slow)
 
        assert self.cb._failure_count == 1
        print("✅ [UNIT] Timeout correctly increments failure count")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_half_open_then_closed_on_success(self):
        """
        After recovery_timeout elapses, circuit moves to HALF_OPEN.
        A successful probe call then closes the circuit again.
        """
        async def bad():
            raise RuntimeError("down")
 
        async def good():
            return "recovered"
 
        # Trip the circuit
        for _ in range(self.cb.failure_threshold):
            with pytest.raises(RuntimeError):
                await self.cb.call(bad)
 
        assert self.cb.state == CircuitState.OPEN
 
        # Manually rewind the last failure time to simulate elapsed recovery_timeout
        self.cb._last_failure_time -= self.cb.recovery_timeout + 1
 
        # State check triggers OPEN → HALF_OPEN transition
        assert self.cb.state == CircuitState.HALF_OPEN
        print("✅ [UNIT] Circuit transitioned to HALF_OPEN after recovery timeout")
 
        # Successful probe → CLOSED
        result = await self.cb.call(good)
        assert result == "recovered"
        assert self.cb.state == CircuitState.CLOSED
        print("✅ [UNIT] Successful probe closed the circuit")
 
    # ------------------------------------------------------------------ #
 
    @pytest.mark.asyncio
    async def test_failure_resets_count_on_success(self):
        """Successful call after partial failures resets the failure counter."""
        async def bad():
            raise RuntimeError("down")
 
        async def good():
            return "ok"
 
        # 2 failures (below threshold of 3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await self.cb.call(bad)
 
        assert self.cb._failure_count == 2
 
        # One success → counter resets
        await self.cb.call(good)
        assert self.cb._failure_count == 0
        assert self.cb.state == CircuitState.CLOSED
        print("✅ [UNIT] Failure count reset after success")
 
 
# =========================================================================== #
#  PART B – Integration Tests (FastAPI HTTP endpoints)                         #
# =========================================================================== #
 
class TestAPIIntegration:
    """
    These tests use FastAPI's synchronous TestClient.
    They reset the circuit breaker state before each test.
    """
 
    def setup_method(self):
        """Reset circuit breaker to CLOSED before each test."""
        from circuit_breaker import CircuitState
        llm_circuit._state = CircuitState.CLOSED
        llm_circuit._failure_count = 0
        llm_circuit._last_failure_time = 0.0
        self.client = TestClient(app, raise_server_exceptions=False)
 
    def test_health_endpoint_returns_student_id_header(self):
        """
        CRITICAL: Every response must include X-Student-ID header.
        Missing this header = automatic zero for Part 3.
        """
        resp = self.client.get("/health")
        assert resp.status_code == 200
        assert "X-Student-ID" in resp.headers, "MISSING X-Student-ID header!"
        print(f"\n✅ [API] X-Student-ID header present: {resp.headers['X-Student-ID']}")
 
    def test_circuit_status_endpoint(self):
        resp = self.client.get("/circuit-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["state"] == "CLOSED"
        assert "failure_count" in data
        print("✅ [API] /circuit-status returns correct schema")
 
    def test_generate_endpoint_happy_path(self):
        """When LLM is healthy, response comes from 'llm' source."""
        import studysync as m
        original = m.LLM_SHOULD_FAIL
        m.LLM_SHOULD_FAIL = False
 
        resp = self.client.post("/api/generate", json={"prompt": "Explain recursion"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "llm"
        assert data["circuit_state"] == "CLOSED"
        assert "X-Student-ID" in resp.headers
        print("✅ [API] Happy path: LLM responded, circuit CLOSED")
 
        m.LLM_SHOULD_FAIL = original
 
    def test_generate_returns_fallback_when_circuit_open(self):
        """
        When we manually open the circuit, the endpoint must return a fallback
        response instantly — not attempt the LLM call.
        """
        from circuit_breaker import CircuitState
        # Force circuit open
        llm_circuit._state = CircuitState.OPEN
        llm_circuit._last_failure_time = time.monotonic()
 
        start = time.monotonic()
        resp = self.client.post("/api/generate", json={"prompt": "test"})
        elapsed = time.monotonic() - start
 
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "fallback"
        assert elapsed < 2.0, f"Fallback should be instant, took {elapsed:.2f}s"
        print(f"✅ [API] Open circuit returned fallback in {elapsed:.4f}s")
 
 
# =========================================================================== #
#  PART C – Standalone Demo (run with: python test_circuit_breaker.py)         #
# =========================================================================== #
 
async def run_demo():
    """
    Full end-to-end demonstration without pytest.
    Simulates the LLM crashing and shows the circuit breaker protecting the app.
    """
    print("\n" + "="*65)
    print("  CIRCUIT BREAKER DEMO – StudySync LLM Fault Tolerance")
    print("="*65)
 
    cb = CircuitBreaker(
        name="LLM-DEMO",
        failure_threshold=3,
        recovery_timeout=5.0,
        call_timeout=2.0,
    )
 
    # ── Simulate LLM going down ──────────────────────────────────────── #
    async def broken_llm(prompt: str) -> str:
        print(f"  [LLM] Attempting call… (will hang/fail)")
        await asyncio.sleep(10)          # simulates 60-second real hang
        return "answer"
 
    async def healthy_llm(prompt: str) -> str:
        await asyncio.sleep(0.05)
        return f"Study summary for: {prompt}"
 
    FALLBACK = "AI tutor is temporarily unavailable. Please try again later."
 
    async def protected_call(prompt: str, llm_fn) -> dict:
        try:
            answer = await cb.call(llm_fn, prompt)
            return {"answer": answer, "source": "llm", "state": cb.state.value}
        except CircuitBreakerOpenError:
            return {"answer": FALLBACK, "source": "FALLBACK (circuit open)", "state": cb.state.value}
        except asyncio.TimeoutError:
            return {"answer": FALLBACK, "source": "FALLBACK (timeout)", "state": cb.state.value}
 
    print("\n📌 Phase 1 – LLM is DOWN. Sending 5 requests…\n")
    for i in range(1, 6):
        result = await protected_call(f"Question {i}", broken_llm)
        print(f"  Request {i}: source={result['source']} | circuit={result['state']}")
        print(f"             answer='{result['answer'][:60]}'\n")
 
    print("\n📌 Phase 2 – Waiting for recovery timeout (5s)…\n")
    await asyncio.sleep(5.5)
 
    print("\n📌 Phase 3 – LLM is BACK UP. Sending probe request…\n")
    result = await protected_call("Probe question", healthy_llm)
    print(f"  Probe:     source={result['source']} | circuit={result['state']}")
    print(f"             answer='{result['answer'][:60]}'\n")
 
    print("\n📌 Phase 4 – Sending 3 more requests (circuit should be CLOSED)…\n")
    for i in range(1, 4):
        result = await protected_call(f"Normal question {i}", healthy_llm)
        print(f"  Request {i}: source={result['source']} | circuit={result['state']}")
 
    print("\n" + "="*65)
    print("  DEMO COMPLETE")
    print("  Key result: once the circuit opened, requests got instant")
    print("  fallback responses instead of waiting 60 seconds each.")
    print("="*65 + "\n")
 
 
if __name__ == "__main__":
    asyncio.run(run_demo())