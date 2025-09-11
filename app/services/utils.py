import re
DRIVETRAIN_TOKENS = {"4matic","xdrive","awd","rwd","fwd","quattro"}

def normalize_token(s: str) -> str:
    if s is None:
        return ""
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def normalize_ymmt(year:int, make:str, model:str, trim:str|None) -> tuple[str,str]:
    # Handle None values safely
    year = year or 0
    make_n = normalize_token(make)
    model_n = normalize_token(model)
    trim_n = normalize_token(trim) if trim else ""
    trim_n = " ".join([t for t in trim_n.split() if t not in DRIVETRAIN_TOKENS])
    ymmt = f"{year} {make_n} {model_n} {trim_n}".strip()
    ymm = f"{year} {make_n} {model_n}".strip()
    return ymmt, ymm
