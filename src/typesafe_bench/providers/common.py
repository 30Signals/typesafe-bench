# Per-request timeout (seconds). Slowest observed model (kimi-k26) runs
# ~20s/call; this leaves generous headroom while still failing a genuinely
# hung request instead of blocking the whole benchmark run.
REQUEST_TIMEOUT_S = 60.0

SYSTEM_PROMPT = """\
You are a structured-decision engine. You will be given the content of a support
ticket and a set of typed questions. Answer ALL questions about the ticket and
return ONLY a single JSON object, no prose, no markdown fences.

Question types:
- "noul": answer with a probability between 0 and 1 that the answer is yes.
- "choice": answer with exactly one of the listed option keys.
- "score": answer with exactly one of the listed level keys (the part before
  the colon in each criterion).

Output shape: {"<question_id>": <answer>, ...} with one key per question,
using the same question ids you were given.
"""


def strip_json_fences(raw: str) -> str:
    """Some models wrap JSON in ```json ... ``` fences despite instructions
    not to. Strip them before parsing rather than failing the call."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[: -3]
        elif "```" in text:
            text = text.rsplit("```", 1)[0]
    return text.strip()


def normalize_endpoint(endpoint: str) -> str:
    """Accept either a full endpoint URL or just an Azure AI Foundry resource
    name (e.g. from AZURE_FOUNDRY_ENDPOINT=my-resource-northcentralus) and
    turn the latter into the resource's base endpoint."""
    endpoint = endpoint.strip().rstrip("/")
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"https://{endpoint}.services.ai.azure.com"
