"""
GenAI App - FastAPI + Google Gemini (deployment-ready)
------------------------------------------------------
This is the ONE application we deploy to both Hugging Face Spaces and Azure
Container Apps in Session 4. The app logic is deliberately unchanged from the
container we built in Session 3 - what changes across this session is only
*where* and *how* it runs.

Design choices that make it cloud-portable:
- Reads the model key from GEMINI_API_KEY *or* GOOGLE_API_KEY, so the same code
  works with the key already present in ../../module3_agents/.env (GOOGLE_API_KEY).
- Binds to the port given by the PORT env var (default 8000). Platforms like
  Azure Container Apps / HF Docker Spaces inject a port; honoring PORT means the
  same image runs everywhere with no code change.

Endpoints:
    GET  /                -> welcome + endpoint map
    GET  /health          -> health check (used by Azure/HF health probes)
    POST /api/generate    -> generate an AI response from a prompt
    GET  /api/history     -> list recent generations (in-memory)
    DELETE /api/history    -> clear history

Local run:
    pip install -r requirements.txt
    uvicorn main:app --reload
    Docs: http://localhost:8000/docs
"""

import os
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from google import genai
from pydantic import BaseModel, Field

# Load environment variables from a local .env if present (harmless in the cloud,
# where the platform injects env vars directly).
load_dotenv()

# Accept either name. The .env in module3_agents ships GOOGLE_API_KEY; the PDF and
# Session 3 used GEMINI_API_KEY. Supporting both means no one has to rename a key.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

if not GEMINI_API_KEY:
    print("WARNING: no GEMINI_API_KEY / GOOGLE_API_KEY found in environment!")
    print("Set one in .env or pass it as a platform secret. Running in degraded mode.")
    client = None
else:
    client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI(
    title="GenAI App",
    description="The one Session 5 Demo",
    version="1.0.0",
)

# In-memory chat history. Fine for a demo; in production this would live in a
# managed store (Azure Blob / Cosmos DB, or GCP's Firestore/Cloud Storage).
chat_history: List[dict] = []


class PromptRequest(BaseModel):
    """Request body for POST /api/generate."""

    prompt: str = Field(..., min_length=1, max_length=5000, description="User prompt for AI")
    model: Optional[str] = Field(
        default="gemini-2.5-flash",
        description="A Gemini llm model that needs to be used",
    )
    temperature: Optional[float] = Field(
        default=0.7, ge=0.0, le=1.0, description="Creativity (0-1)"
    )
    max_tokens: Optional[int] = Field(
        default=1000, ge=1, le=8000, description="Max response length"
    )


class AIResponse(BaseModel):
    """A single generated response."""

    id: int
    prompt: str
    response: str
    model: str
    timestamp: str
    success: bool


class ChatHistory(BaseModel):
    """History listing."""

    total_chats: int
    history: List[AIResponse]


def generate_ai_response(
    prompt: str,
    model_name: str = "gemini-2.5-flash",
    temperature: float = 0.7,
    max_tokens: int = 1000,
) -> str:
    """Call Gemini and return the generated text."""
    if not client:
        raise HTTPException(status_code=503, detail="Gemini API client not initialized")

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        return response.text
    except Exception as exc:  # noqa: BLE001 - surface the provider error to the caller
        raise HTTPException(status_code=500, detail=f"Gemini API Error: {exc}")


@app.get("/")
async def root():
    """Welcome endpoint - lists the available routes."""
    return {
        "message": "Welcome to the GenAI App!",
        "description": "AI-powered application using FastAPI and Google Gemini",
        "endpoints": {
            "docs": "/docs",
            "health": "/health",
            "generate": "/api/generate (POST)",
            "history": "/api/history (GET)",
            "clear_history": "/api/history (DELETE)",
        },
    }


@app.get("/health")
async def health_check():
    """Health check used by Azure Container Apps / HF probes and by our curl tests."""
    api_key_configured = bool(GEMINI_API_KEY)
    return {
        "status": "healthy" if api_key_configured else "degraded",
        "api_key_configured": api_key_configured,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/api/generate", response_model=AIResponse)
async def generate_response(request: PromptRequest):
    """Generate an AI response from a prompt and store it in history."""
    if not GEMINI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Model key not configured. Set GEMINI_API_KEY or GOOGLE_API_KEY.",
        )

    ai_response = generate_ai_response(
        prompt=request.prompt,
        model_name=request.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
    )

    response_obj = {
        "id": len(chat_history) + 1,
        "prompt": request.prompt,
        "response": ai_response,
        "model": request.model,
        "timestamp": datetime.now().isoformat(),
        "success": True,
    }
    chat_history.append(response_obj)
    return response_obj


@app.get("/api/history", response_model=ChatHistory)
async def get_history(limit: Optional[int] = None):
    """Return chat history, optionally limited to the most recent `limit` items."""
    history = chat_history if not limit else chat_history[-limit:]
    return {"total_chats": len(chat_history), "history": history}


@app.delete("/api/history")
async def clear_history():
    """Clear all stored chat history."""
    global chat_history
    count = len(chat_history)
    chat_history = []
    return {
        "message": f"Successfully cleared {count} chat(s) from history",
        "timestamp": datetime.now().isoformat(),
    }


# Local dev entrypoint. In containers the CMD in the Dockerfile runs uvicorn instead.
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
