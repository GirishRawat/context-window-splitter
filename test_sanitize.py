import re

def sanitize_llm_output(raw_text: str) -> str | None:
    match = re.search(r"(define\s+.*?^})", raw_text, re.DOTALL | re.MULTILINE)
    if match:
        return match.group(1).strip()
    start_idx = raw_text.find("define ")
    end_idx = raw_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
        candidate = raw_text[start_idx:end_idx+1].strip()
        if candidate.startswith("define ") and candidate.endswith("}"):
            return candidate
    return None

with open('/Users/girishrawat/.gemini/antigravity-ide/brain/1400bc98-5247-471b-a1a0-9a163823c660/.system_generated/tasks/task-1080.log', 'r') as f:
    text = f.read()
idx = text.find("RAW RESPONSE:")
if idx != -1:
    raw_text = text[idx:]
    print("Sanitized:", sanitize_llm_output(raw_text) is not None)
