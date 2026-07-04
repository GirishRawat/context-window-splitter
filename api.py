from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import traceback
import httpx

# Import the parsing/triage engines from the project
from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.config import PipelineConfig, TriageConfig, OllamaConfig

app = FastAPI(title="LLVM IR Parsing API")

# Allow CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ParseRequest(BaseModel):
    ir_text: str

class FunctionRecordOut(BaseModel):
    name: str
    original_ir: str

class ParseResponse(BaseModel):
    preamble: str
    functions: list[FunctionRecordOut]
    error: str | None = None

@app.post("/api/parse", response_model=ParseResponse)
def parse_ir(request: ParseRequest):
    try:
        parsed = parse_module(request.ir_text)
        functions = [
            FunctionRecordOut(name=fn.name, original_ir=fn.original_ir)
            for fn in parsed.functions
        ]
        return ParseResponse(
            preamble=parsed.preamble,
            functions=functions
        )
    except Exception as e:
        # Return error safely to UI
        return ParseResponse(
            preamble="",
            functions=[],
            error=str(e) + "\n" + traceback.format_exc()
        )


class TriageRequest(BaseModel):
    ir_text: str
    complexity_threshold: int = 5


class FunctionTriageOut(BaseModel):
    name: str
    original_ir: str
    complexity: int
    token_count: int
    triaged_out: bool


class TriageResponse(BaseModel):
    preamble: str
    functions: list[FunctionTriageOut]
    threshold: int
    error: str | None = None


@app.post("/api/triage", response_model=TriageResponse)
def triage_ir(request: TriageRequest):
    try:
        parsed = parse_module(request.ir_text)
        config = PipelineConfig(
            triage=TriageConfig(complexity_threshold=request.complexity_threshold)
        )
        triage_module(parsed, config)
        functions = [
            FunctionTriageOut(
                name=fn.name,
                original_ir=fn.original_ir,
                complexity=fn.complexity,
                token_count=fn.token_count,
                triaged_out=fn.triaged_out,
            )
            for fn in parsed.functions
        ]
        return TriageResponse(
            preamble=parsed.preamble,
            functions=functions,
            threshold=request.complexity_threshold,
        )
    except Exception as e:
        return TriageResponse(
            preamble="",
            functions=[],
            threshold=request.complexity_threshold,
            error=str(e) + "\n" + traceback.format_exc(),
        )

class RouteRequest(BaseModel):
    ir_text: str
    complexity_threshold: int = 5
    mock_llm: bool = False  # Default to real Ollama inference (free & local)

class FunctionRouteOut(BaseModel):
    name: str
    original_ir: str
    complexity: int
    token_count: int
    triaged_out: bool
    assigned_model: str | None
    llm_output: str | None

class RouteResponse(BaseModel):
    preamble: str
    functions: list[FunctionRouteOut]
    error: str | None = None

@app.post("/api/route", response_model=RouteResponse)
def route_ir(request: RouteRequest):
    try:
        from llmcompile.phases.p3_route import route_module
        from unittest.mock import patch, MagicMock
        
        parsed = parse_module(request.ir_text)
        config = PipelineConfig(
            triage=TriageConfig(complexity_threshold=request.complexity_threshold)
        )
        triage_module(parsed, config)
        
        if request.mock_llm:
            # Mock mode: for demos/development when Ollama isn't running
            with patch('llmcompile.phases.p3_route.litellm') as mock_litellm:
                async def fake_completion(*args, **kwargs):
                    mock_response = MagicMock()
                    mock_response.choices = [MagicMock()]
                    # Generate a dummy LLM output for visualization
                    orig = kwargs.get("messages", [])[1].get("content", "")
                    body = orig.split("Optimize this LLVM IR function:\n\n")[-1]
                    
                    if "add i32" in body:
                        body = body.replace("add i32", "shl i32")
                    else:
                        body = body.replace("{\n", "{\n  ; optimized by mocked LLM\n")
                    
                    mock_response.choices[0].message.content = body
                    return mock_response
                    
                mock_litellm.acompletion = fake_completion
                # Also mock the health check so it doesn't try to reach Ollama
                with patch('llmcompile.phases.p3_route._check_ollama_health', return_value=True):
                    route_module(parsed, config)
        else:
            # Real mode: uses Ollama local models (zero cost)
            route_module(parsed, config)

        functions = [
            FunctionRouteOut(
                name=fn.name,
                original_ir=fn.original_ir,
                complexity=fn.complexity,
                token_count=fn.token_count,
                triaged_out=fn.triaged_out,
                assigned_model=fn.assigned_model,
                llm_output=fn.llm_output,
            )
            for fn in parsed.functions
        ]
        return RouteResponse(
            preamble=parsed.preamble,
            functions=functions
        )
    except Exception as e:
        return RouteResponse(
            preamble="",
            functions=[],
            error=str(e) + "\n" + traceback.format_exc()
        )


# ---------------------------------------------------------------------------
# Ollama status endpoint — used by the UI to show connection state
# ---------------------------------------------------------------------------

class OllamaModelInfo(BaseModel):
    name: str
    size_gb: float

class OllamaStatusResponse(BaseModel):
    running: bool
    base_url: str
    models: list[OllamaModelInfo]
    error: str | None = None

@app.get("/api/ollama/status", response_model=OllamaStatusResponse)
async def ollama_status():
    """Check if Ollama is running and list available models."""
    config = PipelineConfig()
    base_url = config.ollama.base_url
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/tags")
            
        if resp.status_code == 200:
            data = resp.json()
            models = [
                OllamaModelInfo(
                    name=m.get("name", "unknown"),
                    size_gb=round(m.get("size", 0) / (1024**3), 2)
                )
                for m in data.get("models", [])
            ]
            return OllamaStatusResponse(
                running=True,
                base_url=base_url,
                models=models
            )
        else:
            return OllamaStatusResponse(
                running=False,
                base_url=base_url,
                models=[],
                error=f"Ollama returned status {resp.status_code}"
            )
    except Exception as e:
        return OllamaStatusResponse(
            running=False,
            base_url=base_url,
            models=[],
            error=str(e)
        )


class VerifyRequest(BaseModel):
    original_ir: str
    candidate_ir: str

class VerifyResponse(BaseModel):
    verdict: str
    counterexample: str | None = None
    error: str | None = None

@app.post("/api/verify", response_model=VerifyResponse)
def verify_ir(request: VerifyRequest):
    try:
        from llmcompile.verification.alive import check_syntax, verify_refinement
        from llmcompile.config import VerificationConfig
        from llmcompile.models import Verdict
        
        orig_clean = request.original_ir.strip()
        cand_clean = request.candidate_ir.strip()
        
        config = VerificationConfig()

        
        # 1. Syntax check
        if not check_syntax(request.candidate_ir, config):
            return VerifyResponse(verdict=Verdict.SYNTAX_FAIL.value)
            
        # 2. Semantic refinement check
        verdict, cex = verify_refinement(request.original_ir, request.candidate_ir, config)
        
        return VerifyResponse(
            verdict=verdict.value,
            counterexample=cex
        )
    except Exception as e:
        return VerifyResponse(
            verdict="unsupported",
            error=str(e) + "\n" + traceback.format_exc()
        )
