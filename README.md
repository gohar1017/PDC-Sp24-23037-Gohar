Ali Gohar | Student ID: BSCS 23037

 PDC-Sp24-23037-Ali Gohar

**Course:** Parallel and Distributed Computing (PDC)  
**Assignment:** 2 – Building Resilient Distributed Systems  
**Problem Solved:** Problem 3 – Fault Tolerance (Circuit Breaker for LLM API)

---

## What This Does

This project implements the **Circuit Breaker** pattern to protect a FastAPI backend from a slow/failing external LLM API.

Without the fix, one hanging LLM call blocks the entire server for 60 seconds.  
With the fix, the circuit opens after 3 failures and all subsequent requests get an instant fallback response.

---

## Project Structure

```
.
├── main.py                 # FastAPI app (protected + unprotected endpoints)
├── circuit_breaker.py      # Circuit Breaker pattern implementation
├── middleware.py           # X-Student-ID header middleware (required for grading)
├── test_circuit_breaker.py # Automated tests + standalone demo
├── requirements.txt
└── report/
    └── report.pdf          # Parts 1 & 2 written report
```

---

## How to Run

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Run the server (LLM healthy)

```bash
uvicorn main:app --reload
```

### 3. Run the server (LLM failing — for demo)

```bash
LLM_SHOULD_FAIL=true uvicorn main:app --reload
```

### 4. Test the endpoints manually

```bash
# Health check (verify X-Student-ID header is present)
curl -i http://localhost:8000/health

# Circuit breaker status
curl http://localhost:8000/circuit-status

# Protected endpoint (with circuit breaker)
curl -X POST http://localhost:8000/api/generate \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Explain binary search"}'

# Unprotected endpoint (hangs when LLM fails — the "before" state)
curl -X POST http://localhost:8000/api/generate/raw \
     -H "Content-Type: application/json" \
     -d '{"prompt": "Explain binary search"}'
```

### 5. Run automated tests

```bash
pytest test_circuit_breaker.py -v
```

### 6. Run the standalone demo (no server needed)

```bash
python test_circuit_breaker.py
```

---

## Grading Header

Every API response includes:

```
X-Student-ID: [YOUR-STUDENT-ID]
```

This is injected by `middleware.py` via a FastAPI `BaseHTTPMiddleware`.

---

## Key API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/circuit-status` | View circuit breaker state |
| POST | `/api/generate` | LLM call WITH circuit breaker ✅ |
| POST | `/api/generate/raw` | LLM call WITHOUT protection ❌ |

---

## Demo Video

[Insert YouTube/Loom link here]
