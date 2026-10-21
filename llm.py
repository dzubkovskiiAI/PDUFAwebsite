"""One function, ask(), in front of either Gemini or Claude. Choose with .env (see README)."""
import json
import os
import time

from . import config


def client():
    if config.PROVIDER == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set. Put it in the .env file in the project folder.")
        from google import genai          # imported lazily so tests do not need the SDK
        return genai.Client(api_key=key)
    import anthropic
    return anthropic.Anthropic()


def ask(cl, system, prompt, web=False, max_tokens=1500):
    if config.PROVIDER == "gemini":
        return _gemini(cl, system, prompt, web)
    return _claude(cl, system, prompt, web, max_tokens)


def _claude(cl, system, prompt, web, max_tokens):
    kw = {}
    if web:
        kw["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5,
                        "blocked_domains": config.AGGREGATORS}]
    resp = cl.messages.create(model=config.MODEL, max_tokens=max_tokens, system=system,
                              messages=[{"role": "user", "content": prompt}], **kw)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _gemini(cl, system, prompt, web):
    from google.genai import types
    # Gemini's API cannot exclude domains server-side. Aggregators are blocked after the fact in
    # validate.clean(), and the prompts also tell the model not to use them.
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=8192,            # generous: reasoning tokens count against this limit
        tools=[types.Tool(google_search=types.GoogleSearch())] if web else None)
    for attempt in range(5):
        if config.CALL_DELAY:
            time.sleep(config.CALL_DELAY)
        try:
            resp = cl.models.generate_content(model=config.MODEL, contents=prompt, config=cfg)
            return resp.text or ""
        except Exception as ex:
            msg = str(ex)
            transient = any(k in msg for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if transient and attempt < 4:
                wait = 20 * (attempt + 1)
                print(f"  rate limited or busy; waiting {wait}s")
                time.sleep(wait)
                continue
            raise
    return ""


def parse_json(text, open_, close_):
    """Tolerant JSON extraction: strips fences and prose, repairs a truncated array."""
    a = text.find(open_)
    if a < 0:
        return None
    b = text.rfind(close_)
    chunk = text[a:b + 1] if b > a else text[a:]
    try:
        return json.loads(chunk)
    except ValueError:
        pass
    if open_ == "[":
        k = chunk.rfind("}")
        if k > 0:
            try:
                return json.loads(chunk[:k + 1] + "]")
            except ValueError:
                pass
    return None
