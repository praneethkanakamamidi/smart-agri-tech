"""
Structured output helpers. Whatever the provider mechanism (forced tool call, json_schema
response format, or plain prompting), the result is always validated with pydantic here.
"""
import copy
import json
import re

from pydantic import BaseModel, ValidationError

from src.agents.llm.errors import LLMOutputInvalid

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def json_schema(model: type[BaseModel]) -> dict:
    """The model's JSON schema with every $ref inlined (some providers reject $defs)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node and node["$ref"].startswith("#/$defs/"):
                target = copy.deepcopy(defs[node["$ref"].split("/")[-1]])
                extra = {k: v for k, v in node.items() if k != "$ref"}
                return resolve({**target, **extra})
            return {k: resolve(v) for k, v in node.items()}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def schema_instructions(model: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object and nothing else. It must validate against this JSON schema:\n"
        + json.dumps(json_schema(model), ensure_ascii=False)
    )


def extract_json(text: str):
    """Parse the first JSON object in `text` (tolerates code fences and leading prose)."""
    cleaned = _FENCE.sub("", (text or "").strip())
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    start = cleaned.find("{")
    while start != -1:
        depth, in_string, escape = 0, False, False
        for index in range(start, len(cleaned)):
            ch = cleaned[index]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[start:index + 1])
                    except ValueError:
                        break
        start = cleaned.find("{", start + 1)
    raise LLMOutputInvalid("no JSON object found in model output")


def validate(model: type[BaseModel], payload) -> BaseModel:
    if isinstance(payload, str):
        payload = extract_json(payload)
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()[:8])
        raise LLMOutputInvalid(f"output failed schema validation: {problems}") from e


def repair_prompt(error: LLMOutputInvalid) -> str:
    return (
        f"Your previous reply could not be used ({error}). Reply again with only a corrected JSON object "
        "that validates against the schema. Do not add commentary."
    )
