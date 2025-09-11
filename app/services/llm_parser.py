
import os, time
from openai import OpenAI

SCHEMA = {
    "name": "VehicleRecord",
    "schema": {
        "type": "object",
        "properties": {
            "year": {"type": ["integer", "null"]},
            "make": {"type": ["string", "null"]},
            "model": {"type": ["string", "null"]},
            "trim": {"type": ["string", "null"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1}
        },
        "required": ["year","make","model","trim","confidence"],
        "additionalProperties": False
    },
    "strict": True
}

SYS_PROMPT = "You are a VIN-decoder-like vehicle entity extraction engine. Extract YEAR, MAKE, MODEL, TRIM from messy listing text. Output MUST follow the JSON schema. If unsure about a field, set it to null. Capture price-impacting trims (e.g., 2LT/3LT, Z51, Performance, Premium Plus, AMG, quattro/xDrive/4MATIC). Confidence reflects certainty."

class VehicleParser:
    def __init__(self, model: str = None, max_retries: int = 3, request_timeout: float = 30.0):
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set. Add it in Replit Secrets.")
        self.client = OpenAI(api_key=api_key)
        self.model = model or "gpt-4.1-mini"
        self.max_retries = max_retries
        self.request_timeout = request_timeout

    def parse(self, text: str) -> dict:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                resp = self.client.responses.create(
                    model=self.model,
                    input=text,
                    system=SYS_PROMPT,
                    response_format={"type":"json_schema","json_schema":SCHEMA},
                    timeout=self.request_timeout,
                )
                out = resp.output[0].content[0].parsed
                return {
                    "year": out.get("year"),
                    "make": out.get("make"),
                    "model": out.get("model"),
                    "trim": out.get("trim"),
                    "confidence": float(out.get("confidence", 0.0) or 0.0)
                }
            except Exception as e:
                last_err = e
                time.sleep(0.8*(attempt+1))
        raise last_err
