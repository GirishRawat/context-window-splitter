from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import traceback

# Import the parsing/triage engines from the project
from llmcompile.phases.p1_parse import parse_module
from llmcompile.phases.p2_triage import triage_module
from llmcompile.config import PipelineConfig, TriageConfig

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
