import json
import os

from baf.cases import cases, prompt
from .common import Fault, request_json, serve


class ModelProxy:
    def __init__(self, mode="replay", url="", key="", model="", extra=None,
                 proxy_url="", proxy_socket="", timeout=90):
        if mode not in ("replay", "live"):
            raise ValueError("LLM_MODE must be replay or live")
        if mode == "live" and (not url.startswith("https://") or not key or not model):
            raise ValueError("Live mode requires an HTTPS LLM_URL, LLM_API_KEY and LLM_MODEL")
        self.mode, self.url, self.key, self.model = mode, url, key, model
        if proxy_url and not proxy_url.startswith(("http://", "https://")):
            raise ValueError("LLM_HTTP_PROXY must be an HTTP(S) proxy URL")
        if proxy_url and proxy_socket:
            raise ValueError("Configure only one LLM proxy transport")
        if not 1 <= timeout <= 120:
            raise ValueError("LLM_TIMEOUT must be between 1 and 120 seconds")
        self.proxy_url, self.proxy_socket, self.timeout = proxy_url, proxy_socket, timeout
        self.extra = extra or {}
        if not isinstance(self.extra, dict):
            raise ValueError("LLM_EXTRA_JSON must be an object")
        if any(key in self.extra and (type(self.extra[key]) is not int or self.extra[key] != 1)
               for key in ("n", "best_of")):
            raise ValueError("Only one completion per provider request is allowed")
        if type(self.extra.get("max_tokens", 2048)) is not int or not 1 <= self.extra.get("max_tokens", 2048) <= 4096:
            raise ValueError("max_tokens must be an integer between 1 and 4096")
        if "max_completion_tokens" in self.extra:
            raise ValueError("Use max_tokens to keep the provider output budget explicit")
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
            payload = {**self.extra, "model": self.model, "messages": body["messages"], "stream": False}
            payload.setdefault("max_tokens", 2048)
            # Some OpenAI-compatible providers reject tools=[] (HTTP 400).
            if body["tools"]:
                payload["tools"] = body["tools"]
            response = request_json(self.url.rstrip("/") + "/chat/completions",
                payload, self.key, timeout=self.timeout,
                proxy_url=self.proxy_url, proxy_socket=self.proxy_socket)
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
                     json.loads(os.getenv("LLM_EXTRA_JSON") or "{}"),
                     os.getenv("LLM_HTTP_PROXY", ""), os.getenv("LLM_PROXY_SOCKET", ""),
                     float(os.getenv("LLM_TIMEOUT", "90"))), os.environ["INTERNAL_TOKEN"])
