import os, sys, traceback
from typing import Any, Dict, Optional
from openai import OpenAI
from dotenv import load_dotenv


class OpenAIWrapper:
    """Wrapper for OpenAI Responses API with automatic cost accounting."""

    # USD per 1M tokens
    _PRICING = {
        "gpt-5": {"input": 1.250, "output": 10.000},
        "gpt-5-mini": {"input": 0.250, "output": 2.000},
        "gpt-5-nano": {"input": 0.050, "output": 0.400},
    }

    # Web search flat fee (per tool call)
    _WEB_SEARCH_COST_PER_CALL = 0.01  # $10 / 1,000 tool calls

    def __init__(self, api_key: Optional[str] = None, timeout=1000):
        load_dotenv()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not found.")
        self.client = OpenAI(api_key=self.api_key, timeout=timeout)
        self.timeout = timeout

    def query(
        self,
        prompt: str,
        model: str = "gpt-5-mini",
        tools: Optional[list] = None,
        response_format: str = "text",
    ) -> Dict[str, Any]:
        """
        Send a prompt to the OpenAI Responses API and return:
          - text_response: str
          - raw_response:  obj
          - cost:          float (USD, includes reasoning + per-search fee)
        """
        try:
            if model not in self._PRICING:
                raise ValueError(f"Unsupported model '{model}'")

            fmt = {"format": {"type": response_format}}
            r = self.client.responses.create(
                model=model, input=prompt, tools=tools, text=fmt, timeout=self.timeout
            )

            # ---- extract assistant text ----
            msg = next((m for m in r.output if getattr(m, "role", "") == "assistant"), None)
            text_response = ""
            if msg:
                text_response = "".join(
                    (p.text for p in getattr(msg, "content", []) if hasattr(p, "text"))
                ).strip()

            # ---- token usage ----
            usage = getattr(r, "usage", None)
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
            reasoning_tok = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0
            billable_out_tok = out_tok + max(0, reasoning_tok - out_tok)

            # ---- token costs ----
            price = self._PRICING[model]
            cost = (in_tok / 1e6) * price["input"] + (billable_out_tok / 1e6) * price["output"]

            # ---- count web_search tool calls ----
            web_calls = 0
            if hasattr(r, "output") and isinstance(r.output, list):
                for item in r.output:
                    if getattr(item, "type", "") == "web_search_call":
                        web_calls += 1
            # Add flat fee per call
            cost += web_calls * self._WEB_SEARCH_COST_PER_CALL

            return {
                "text_response": text_response,
                "raw_response": r,
                "cost": round(cost, 6),
            }

        except Exception as e:
            print(f"[OpenAIWrapper] {type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stdout)
            return {"text_response": "", "raw_response": None, "cost": 0.0}