import json
import os

from baf.cases import cases, prompt
from .common import Fault, request_json, serve


class ModelProxy:
    def __init__(self, mode="replay", url="", key="", model="", extra=None):
        if mode not in ("replay", "live"):
            raise ValueError("LLM_MODE must be replay or live")
        if mode == "live" and (not url.startswith("https://") or not key or not model):
            raise ValueError("Live mode requires an HTTPS LLM_URL, LLM_API_KEY and LLM_MODEL")
        self.mode, self.url, self.key, self.model = mode, url, key, model
        self.extra = extra or {}
        if set(self.extra) & {"model", "messages", "tools", "stream"}:
            raise ValueError("LLM_EXTRA_JSON cannot override model, messages, tools or stream")

    def health(self):
        return {"status": "ok", "service": "llm-proxy", "v": 0, "mode": self.mode}

    def dispatch(self, body):
        if body.get("op") != "complete" or not isinstance(body.get("messages"), list) or not isinstance(body.get("tools"), list):
            raise Fault("validation", "Expected complete with messages and tools")
        if self.mode == "replay":
            return self.replay(body["messages"])
        try:
            response = request_json(self.url.rstrip("/") + "/chat/completions",
                {**self.extra, "model": self.model, "messages": body["messages"],
                 "tools": body["tools"], "stream": False}, self.key, timeout=20)
            source = response["choices"][0]
            if source.get("finish_reason") not in ("stop", "tool_calls"):
                raise ValueError("Incomplete model response")
            message = source["message"]
            if message.get("role") != "assistant":
                raise ValueError("Invalid role")
            if message.get("content") is not None and (not isinstance(message["content"], str) or len(message["content"]) > 65536):
                raise ValueError("Invalid or oversized assistant content")
            for call in message.get("tool_calls", []):
                if not isinstance(call["id"], str) or not isinstance(call["function"]["arguments"], str):
                    raise ValueError("Invalid tool call")
            return {"v": 0, "message": message, "usage": response.get("usage", {}),
                    "provider": "live", "model": self.model}
        except (Fault, KeyError, ValueError, TypeError, IndexError):
            # Provider errors can echo credentials or request text; never forward their body.
            raise Fault("model", "Provider request failed or returned an invalid completion", 502) from None

    def replay(self, messages):
        users = [i for i, message in enumerate(messages) if message.get("role") == "user"]
        if not users:
            raise Fault("validation", "No user message")
        last = users[-1]
        task = next((case for case in cases() if prompt(case) == messages[last].get("content")), None)
        if task is None:
            return {"v": 0, "provider": "synthetic-replay", "model": "fixture-v1", "usage": {"total_tokens": 0},
                    "message": {"role": "assistant", "content": "Replay mode only supports the bundled BAF prompts. Configure LLM_MODE=live for arbitrary requests."}}
        step = sum(message.get("role") == "tool" for message in messages[last + 1:])
        if step >= len(task["replay"]):
            message = {"role": "assistant", "content": "Synthetic replay finished; the independent checker determines whether the task passed."}
        else:
            tool = task["replay"][step]
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"replay-{task['id']}-{step}", "type": "function",
                "function": {"name": tool["name"], "arguments": json.dumps(tool["arguments"])}}]}
        return {"v": 0, "provider": "synthetic-replay", "model": "fixture-v1", "usage": {"total_tokens": 0}, "message": message}


if __name__ == "__main__":
    serve(ModelProxy(os.getenv("LLM_MODE", "replay"), os.getenv("LLM_PROVIDER_URL", ""),
                     os.getenv("LLM_API_KEY", ""), os.getenv("LLM_MODEL", ""),
                     json.loads(os.getenv("LLM_EXTRA_JSON") or "{}")), os.environ["INTERNAL_TOKEN"])
