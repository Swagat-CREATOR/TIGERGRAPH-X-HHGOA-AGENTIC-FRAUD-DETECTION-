"""Shared Gemini Flash client — ONE model, three pipelines.

The whole comparison rests on P1 (plain RAG), P2 (GraphRAG) and P3 (agentic
GraphRAG) calling the *same* model (`GEMINI_MODEL` in .env, currently
gemini-3.6-flash) so differences in accuracy and token cost are attributable to
the retrieval/agency layer, not the model. This module is that single call site.

Two entry points:
  * ``generate_json`` — one structured-output call (P1, P2, and P3's final
    answer). We ask for application/json, then validate against our own strict
    Pydantic (schema.py) with a bounded repair-retry that feeds the validation
    error back to the model. genai's own schema coercion is skipped on purpose:
    our enums + extra="forbid" + cross-field validators are stricter than what
    response_schema round-trips cleanly.
  * ``run_tool_loop`` — Gemini function-calling (P3's plan->act->observe). The
    model picks tools; we execute them and feed results back until it stops or a
    hard step cap trips.

Token usage (usage_metadata.total_token_count) is accumulated on the LLM
instance so each pipeline can report tokens for the efficiency table.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from dotenv import dotenv_values
from google import genai
from google.genai import types


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON-schema object


@dataclass
class LLM:
    model: str
    _client: genai.Client = field(init=False)
    tokens: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        e = dotenv_values(".env")
        self._client = genai.Client(api_key=e["GEMINI_API_KEY"])

    # placeholder-llm-methods

    def _generate(self, contents, cfg, _tries: int = 8):
        """generate_content with backoff on transient 429/500/503 (the flash
        endpoint returns 503 'high demand' intermittently, sometimes for a minute
        or two — ride it out rather than failing a whole batch run)."""
        import time
        from google.genai import errors
        delay = 4.0
        for i in range(_tries):
            try:
                resp = self._client.models.generate_content(
                    model=self.model, contents=contents, config=cfg)
                self._track(resp)
                return resp
            except errors.APIError as ex:  # noqa: PERF203
                code = getattr(ex, "code", None) or getattr(ex, "status_code", None)
                if code in (429, 500, 503) and i < _tries - 1:
                    time.sleep(delay)
                    delay = min(delay * 1.7, 60.0)
                    continue
                raise

    def _track(self, resp) -> None:
        self.calls += 1
        um = getattr(resp, "usage_metadata", None)
        if um and getattr(um, "total_token_count", None):
            self.tokens += int(um.total_token_count)

    def generate_json(self, system: str, user: str, max_repairs: int = 2) -> dict:
        """One JSON call. Returns the parsed dict (raw model output); the caller
        validates against Pydantic. Retries with the parse error fed back."""
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            temperature=0.0,
        )
        last_err = ""
        for attempt in range(max_repairs + 1):
            resp = self._generate(contents, cfg)
            text = (resp.text or "").strip()
            try:
                return json.loads(text)
            except json.JSONDecodeError as ex:
                last_err = f"{ex}: {text[:200]}"
                contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
                contents.append(types.Content(role="user", parts=[types.Part(
                    text=f"That was not valid JSON ({ex}). Return ONLY the JSON object.")]))
        raise ValueError(f"generate_json failed after retries: {last_err}")

    def run_tool_loop(self, system: str, user: str, tools: list[ToolSpec],
                      dispatch, max_steps: int = 12) -> tuple[str, list[dict]]:
        """Gemini function-calling loop. `dispatch(name, args) -> dict` executes a
        tool. Returns (final model text, list of {step,tool,args,result_summary}).
        The model is told to stop calling tools and summarise when done."""
        decls = [types.FunctionDeclaration(
            name=t.name, description=t.description,
            parameters=t.parameters) for t in tools]
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=decls)],
            temperature=0.0,
        )
        contents = [types.Content(role="user", parts=[types.Part(text=user)])]
        trace: list[dict] = []
        for step in range(max_steps):
            resp = self._generate(contents, cfg)
            cand = resp.candidates[0]
            parts = cand.content.parts or []
            calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
            if not calls:
                return (resp.text or "").strip(), trace
            contents.append(cand.content)
            resp_parts = []
            for fc in calls:
                args = dict(fc.args or {})
                try:
                    result = dispatch(fc.name, args)
                    summary = json.dumps(result)[:300]
                except Exception as ex:  # noqa: BLE001
                    result, summary = {"error": str(ex)}, f"ERROR {ex}"[:300]
                trace.append({"step": step, "tool": fc.name, "args": args,
                              "result_summary": summary})
                resp_parts.append(types.Part.from_function_response(
                    name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=resp_parts))
        return "STOP: max tool steps reached", trace


@dataclass
class GroqLLM:
    """Drop-in fallback for :class:`LLM` speaking any OpenAI-compatible chat API.

    Same public surface (``model``/``tokens``/``calls`` + ``generate_json`` +
    ``run_tool_loop``) so the pipelines never learn which provider is behind them.
    Defaults to Groq; ``base_url``/``key_env`` let it also drive other
    OpenAI-compatible gateways (e.g. the xkiro aggregator) when Gemini/Groq are
    quota-capped. Still ONE model across P1/P2/P3, so the comparison stays fair.
    HTTP via ``requests`` (no extra SDK dependency)."""

    model: str
    base_url: str = "https://api.groq.com/openai/v1/chat/completions"
    key_env: str = "GROQ_API_KEY"
    _key: str = field(init=False, repr=False)
    tokens: int = 0
    calls: int = 0

    def __post_init__(self) -> None:
        self._key = dotenv_values(".env")[self.key_env]

    def _post(self, payload: dict, _tries: int = 8) -> dict:
        import time

        import requests
        delay = 4.0
        for i in range(_tries):
            r = requests.post(
                self.base_url, timeout=120,
                headers={"Authorization": f"Bearer {self._key}",
                         "Content-Type": "application/json"},
                # max_tokens caps the completion so input+output stays under the
                # free-tier per-request TPM budget (gpt-oss-120b = 8000 TPM on the
                # on_demand tier; an uncapped request reserves ~4k completion and
                # 413s "Request too large"). Callers may override via payload.
                json={"model": self.model, "temperature": 0.0,
                      "max_tokens": 3000, **payload})
            if r.status_code in (429, 500, 502, 503) and i < _tries - 1:
                time.sleep(delay)
                delay = min(delay * 1.7, 60.0)
                continue
            r.raise_for_status()
            data = r.json()
            self.calls += 1
            self.tokens += int((data.get("usage") or {}).get("total_tokens", 0) or 0)
            return data
        r.raise_for_status()  # exhausted retries on a transient code
        return r.json()

    @staticmethod
    def _extract_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            i, j = text.find("{"), text.rfind("}")
            if 0 <= i < j:
                return json.loads(text[i:j + 1])
            raise

    def generate_json(self, system: str, user: str, max_repairs: int = 2) -> dict:
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
        last_err = ""
        for _ in range(max_repairs + 1):
            data = self._post({"messages": msgs,
                               "response_format": {"type": "json_object"}})
            text = (data["choices"][0]["message"].get("content") or "").strip()
            try:
                return self._extract_json(text)
            except json.JSONDecodeError as ex:
                last_err = f"{ex}: {text[:200]}"
                msgs.append({"role": "assistant", "content": text})
                msgs.append({"role": "user",
                             "content": f"That was not valid JSON ({ex}). "
                                        "Return ONLY the JSON object."})
        raise ValueError(f"generate_json failed after retries: {last_err}")

    def run_tool_loop(self, system: str, user: str, tools: list[ToolSpec],
                      dispatch, max_steps: int = 12) -> tuple[str, list[dict]]:
        specs = [{"type": "function",
                  "function": {"name": t.name, "description": t.description,
                               "parameters": t.parameters}} for t in tools]
        msgs = [{"role": "system", "content": system},
                {"role": "user", "content": user}]
        trace: list[dict] = []
        for step in range(max_steps):
            # Small completion cap: tool-call decisions are short, so this leaves
            # the bulk of the 8000-TPM per-request budget for the growing message
            # history (free-tier ceiling; see _post).
            data = self._post({"messages": msgs, "tools": specs,
                               "tool_choice": "auto", "max_tokens": 1024})
            msg = data["choices"][0]["message"]
            tcs = msg.get("tool_calls") or []
            if not tcs:
                return (msg.get("content") or "").strip(), trace
            msgs.append({"role": "assistant",
                         "content": msg.get("content") or "",
                         "tool_calls": tcs})
            for tc in tcs:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                try:
                    result = dispatch(name, args)
                    summary = json.dumps(result)[:300]
                except Exception as ex:  # noqa: BLE001
                    result, summary = {"error": str(ex)}, f"ERROR {ex}"[:300]
                trace.append({"step": step, "tool": name, "args": args,
                              "result_summary": summary})
                # Cap tool output fed back into context at ~1.2k chars (~340 tok):
                # 4k chars x many steps would push a single request past 8000 TPM.
                msgs.append({"role": "tool", "tool_call_id": tc.get("id"),
                             "content": json.dumps({"result": result})[:1200]})
        return "STOP: max tool steps reached", trace


def make_llm(env_path: str = ".env") -> "LLM | GroqLLM":
    e = dotenv_values(env_path)
    prov = (e.get("LLM_PROVIDER") or "gemini").lower()
    if prov == "groq":
        return GroqLLM(model=e["GROQ_MODEL"])
    if prov == "xkiro":
        # OpenAI-compatible aggregator; base URL is the /v1 root.
        return GroqLLM(model=e["XKIRO_MODEL"],
                       base_url=e["XKIRO_BASE_URL"].rstrip("/") + "/chat/completions",
                       key_env="XKIRO_API_KEY")
    return LLM(model=e["GEMINI_MODEL"])

