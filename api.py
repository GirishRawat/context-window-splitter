from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import traceback

# Import the parsing engine from the project
from llmcompile.phases.p1_parse import parse_module

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
