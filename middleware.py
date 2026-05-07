"""
middleware.py
-------------
FastAPI middleware that injects the mandatory grading header:
 
    X-Student-ID: <YOUR-STUDENT-ID>
 
Every API response — success or error — will carry this header.
Without it, Part 3 receives an automatic zero per the assignment rules.
"""
 
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
 
# ⚠️  REPLACE THIS with your actual Student ID before submission
STUDENT_ID = "BSCS 23037"
 
 
class StudentIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Student-ID"] = STUDENT_ID
        return response
 