"""
main.py
-------
StudySync – FastAPI backend with Circuit Breaker protection around the LLM API.

Endpoints:
  GET  /health                 → Service health check
  GET  /circuit-status         → Inspect circuit breaker state
  POST /api/generate           → Ask the LLM a question (protected by circuit breaker)
  POST /api/generate/raw       → SAME endpoint WITHOUT protection (for before/after demo)

The LLM call is mocked by `_fake_llm_call()` so you can run this with zero
external dependencies. Set LLM_SHOULD_FAIL=True to simulate an outage.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from circuit_breaker import CircuitBreaker, CircuitBreakerOpenError
from middleware import StudentIDMiddleware

# --------------------------------------------------------------------------- #
#  Configuration                                                                #
# --------------------------------------------------------------------------- #

# Flip this to True to simulate the LLM being down (used in the demo / tests)
LLM_SHOULD_FAIL: bool = os.getenv("LLM_SHOULD_FAIL", "false").lower() == "true"

# Circuit breaker tuned for demo purposes (low thresholds so failures are visible quickly)
llm_circuit = CircuitBreaker(
    name="LLM-API",
    failure_threshold=3,       # Open after 3 consecutive failures
    recovery_timeout=15.0,     # Try again after 15 seconds
    call_timeout=5.0,          # Abort any LLM call that takes longer than 5 s
)

# --------------------------------------------------------------------------- #
#  FastAPI app                                                                 #
# --------------------------------------------------------------------------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("StudySync API starting up …")
    yield
    print("StudySync API shutting down …")


app = FastAPI(
    title="StudySync API – Circuit Breaker Demo",
    description="PDC Assignment 2 – Fault Tolerance via Circuit Breaker",
    version="1.0.0",
    lifespan=lifespan,
)

# Attach the mandatory grading middleware (must come AFTER app is created)
app.add_middleware(StudentIDMiddleware)


# --------------------------------------------------------------------------- #
#  Schemas                                                                      #
# --------------------------------------------------------------------------- #

class PromptRequest(BaseModel):
    prompt: str


class LLMResponse(BaseModel):
    answer: str
    source: str          # "llm" | "fallback"
    circuit_state: str


# --------------------------------------------------------------------------- #
#  Mock LLM helper                                                              #
# --------------------------------------------------------------------------- #

async def _fake_llm_call(prompt: str) -> str:
    """
    Simulates a call to an external LLM API.

    When LLM_SHOULD_FAIL is True (or env var LLM_SHOULD_FAIL=true),
    this sleeps for 60 seconds mimicking a hanging upstream — exactly the
    real-world problem described in the assignment.

    Without the circuit breaker, every request would block for 60 s.
    With the circuit breaker, only the first `failure_threshold` requests
    actually hang; after that the circuit opens and all subsequent requests
    get an instant fallback response.
    """
    if LLM_SHOULD_FAIL:
        print(f"[LLM] Simulating 60-second hang for prompt: '{prompt[:40]}...'")
        await asyncio.sleep(60)   # This is what kills the naive server

    # Happy-path: return a mocked answer instantly
    await asyncio.sleep(0.1)      # Simulate a small real-world network delay
    return f"Here is a generated study summary for: '{prompt}'"


# --------------------------------------------------------------------------- #
#  Routes                                                                       #
# --------------------------------------------------------------------------- #

@app.get("/health", tags=["Infra"])
async def health():
    return {"status": "ok", "service": "StudySync API"}


@app.get("/circuit-status", tags=["Infra"])
async def circuit_status():
    """Real-time view of the circuit breaker's internal state."""
    return llm_circuit.get_status()


# ── PROTECTED endpoint (WITH circuit breaker) ────────────────────────────── #

@app.post("/api/generate", response_model=LLMResponse, tags=["LLM"])
async def generate_with_circuit_breaker(body: PromptRequest):
    """
    Calls the LLM API through the circuit breaker.

    Behaviour:
      • CLOSED  → request goes to LLM normally.
      • OPEN    → request is blocked instantly; fallback answer returned.
      • HALF-OPEN → one probe request is sent; if it succeeds, circuit closes.

    The server NEVER hangs waiting for a dead LLM.
    """
    fallback_answer = (
        "Our AI tutor is temporarily unavailable. "
        "Please try again in a few minutes or check your course materials."
    )

    try:
        answer = await llm_circuit.call(_fake_llm_call, body.prompt)
        return LLMResponse(
            answer=answer,
            source="llm",
            circuit_state=llm_circuit.state.value,
        )

    except CircuitBreakerOpenError as e:
        # Circuit is OPEN → instant fallback, no upstream call made
        print(f"[API] Circuit OPEN — returning fallback. Reason: {e}")
        return LLMResponse(
            answer=fallback_answer,
            source="fallback",
            circuit_state=llm_circuit.state.value,
        )

    except asyncio.TimeoutError:
        # The LLM call timed out (circuit breaker's call_timeout exceeded)
        print("[API] LLM call timed out — returning fallback.")
        return LLMResponse(
            answer=fallback_answer,
            source="fallback",
            circuit_state=llm_circuit.state.value,
        )

    except Exception as e:
        # Any other upstream error
        print(f"[API] Unexpected LLM error: {e} — returning fallback.")
        return LLMResponse(
            answer=fallback_answer,
            source="fallback",
            circuit_state=llm_circuit.state.value,
        )


# ── UNPROTECTED endpoint (WITHOUT circuit breaker – for "before" demo) ────── #

@app.post("/api/generate/raw", tags=["LLM"])
async def generate_without_circuit_breaker(body: PromptRequest):
    """
    Calls the LLM API with NO protection whatsoever.

    If LLM_SHOULD_FAIL=true, this endpoint will hang for 60 seconds,
    blocking the server thread and making the app unresponsive for EVERYONE.

    Use this endpoint in the demo to show the broken behaviour, then switch
    to /api/generate to show the fixed behaviour.
    """
    try:
        answer = await _fake_llm_call(body.prompt)
        return {"answer": answer, "source": "llm"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
