"""Opt-in, fixture-only provider recordings and strict offline playback.

Recordings contain actual provider replies, not generated synthetic tool scripts.
Only opaque runtime IDs, operation durations and unittest elapsed time are ignored
when matching contexts. Other changed output deliberately stops replay.
"""
import copy
import datetime
import hashlib
import json
import os
import re
import threading
from pathlib import Path

from baf.cases import cases, prompt
from .common import Fault

FORMAT = "project-a-provider-recording-v1"
MAX_RECORDING = 16 * 1024 * 1024


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def fixture_digest(case):
    return digest({name: (value.encode() if isinstance(value, str) else value).hex()
                   for name, value in case["fixture"].items()})


def context_digest(messages, tools):
    normalized = copy.deepcopy(messages)
    commands = set()
    for message in normalized:
        if message.get("role") == "assistant":
            commands.update(call.get("id") for call in message.get("tool_calls", [])
                            if call.get("function", {}).get("name") == "RunCommand")
        if message.get("role") == "tool":
            try:
                result = json.loads(message["content"])
            except (ValueError, TypeError, KeyError):
                raise Fault("model", "Recorded replay requires structured tool results", 409) from None
            if not isinstance(result, dict):
                raise Fault("model", "Recorded replay requires structured tool results", 409)
            for key in ("session_id", "operation_id", "duration_ms"):
                result.pop(key, None)
            if message.get("tool_call_id") in commands:
                for stream in ("stdout", "stderr"):
                    if isinstance(result.get(stream), str):
                        result[stream] = re.sub(r"(?m)^(Ran \d+ tests? in )\d+(?:\.\d+)?(s\r?)$",
                                                r"\1<elapsed>\2", result[stream])
            message["content"] = result
    return digest({"messages": normalized, "tools": tools})


class RecordingStore:
    def __init__(self, directory, *, writing=False):
        if not directory:
            raise ValueError("Recording mode requires LLM_RECORDING_DIR")
        self.root = Path(directory)
        if writing:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.root.is_dir() or self.root.is_symlink():
            raise ValueError("Recording directory must be an existing real directory")
        self.writing = writing
        self.lock = threading.RLock()
        self.inflight = set()
        self.smoke = {case["id"]: case for case in cases() if case["id"].endswith(".1")}

    def identify(self, body):
        messages = body["messages"]
        if (len(messages) < 2 or messages[0].get("role") != "system"
                or messages[1].get("role") != "user"
                or any(message.get("role") == "user" for message in messages[2:])):
            raise Fault("validation", "Recording requires a fresh benchmark conversation", 400)
        case = next((case for case in self.smoke.values() if messages[1].get("content") == prompt(case)), None)
        if case is None:
            raise Fault("validation", "Recording accepts only the nine exact smoke fixture prompts", 400)
        assistants = [message for message in messages[2:] if message.get("role") == "assistant"]
        return case, len(assistants), context_digest(messages, body["tools"])

    def load(self, case):
        path = self.root / (case["id"] + ".json")
        if path.is_symlink():
            raise Fault("model", "Recording file must not be a symlink", 409)
        try:
            with path.open("rb") as file:
                raw = file.read(MAX_RECORDING + 1)
            if len(raw) > MAX_RECORDING:
                raise ValueError("size")
            value = json.loads(raw)
            if (value.get("format") != FORMAT or value.get("task") != case["id"]
                    or value.get("fixture_sha256") != fixture_digest(case)
                    or value.get("source") != "actual-provider-responses"
                    or not isinstance(value.get("frames"), list)):
                raise ValueError("metadata")
            if not isinstance(value.get("model"), str) or not value["model"]:
                raise ValueError("model")
            for frame in value["frames"]:
                if (not isinstance(frame, dict) or not isinstance(frame.get("context_sha256"), str)
                        or re.fullmatch("[0-9a-f]{64}", frame["context_sha256"]) is None):
                    raise ValueError("frame")
                reply = frame.get("provider_response")
                if (not isinstance(reply, dict) or not isinstance(reply.get("choices"), list)
                        or len(reply["choices"]) != 1 or not isinstance(reply["choices"][0], dict)
                        or not isinstance(reply["choices"][0].get("message"), dict)):
                    raise ValueError("response")
            return value
        except FileNotFoundError:
            return None
        except (OSError, ValueError, TypeError, AttributeError):
            raise Fault("model", "Invalid recording or changed benchmark fixture", 409) from None

    def begin(self, body, model):
        if not self.writing:
            raise Fault("validation", "Recording store is read-only", 400)
        case, step, context = self.identify(body)
        with self.lock:
            saved = self.load(case)
            if case["id"] in self.inflight or saved and (saved.get("complete") or saved.get("failure")):
                raise Fault("model", "Recording already exists; select a new recording directory", 409)
            if saved is None:
                if step != 0:
                    raise Fault("model", "Recording must begin before the first completion", 409)
                saved = {"format": FORMAT, "source": "actual-provider-responses", "task": case["id"],
                         "fixture_sha256": fixture_digest(case), "model": model, "complete": False,
                         "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(), "frames": []}
            if saved["model"] != model or len(saved["frames"]) != step:
                raise Fault("model", "Recording sequence or model differs", 409)
            self.check_history(body, saved, step)
            self.inflight.add(case["id"])
        return case, saved, context

    @staticmethod
    def check_history(body, saved, step):
        assistants = [message for message in body["messages"][2:] if message.get("role") == "assistant"]
        if len(assistants) != step:
            raise Fault("model", "Recorded conversation sequence differs", 409)
        for index, message in enumerate(assistants):
            if message != saved["frames"][index]["provider_response"]["choices"][0]["message"]:
                raise Fault("model", "Recorded assistant history differs", 409)

    def finish(self, ticket, response=None, failure=None, secret=""):
        case, saved, context = ticket
        try:
            if response is not None:
                saved["frames"].append({"context_sha256": context, "provider_response": response})
                source = response["choices"][0]
                saved["complete"] = source.get("finish_reason") == "stop" and not source["message"].get("tool_calls")
            if failure is not None:
                saved["failure"] = failure
                saved["complete"] = False
            raw = json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False).encode()
            if len(raw) > MAX_RECORDING or secret and secret.encode() in raw:
                raise Fault("model", "Recording exceeds limits or contains a credential", 502)
            path = self.root / (case["id"] + ".json")
            temporary = self.root / (case["id"] + ".pending")
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "wb") as file:
                    file.write(raw)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        finally:
            with self.lock:
                self.inflight.discard(case["id"])

    def playback(self, body):
        case, step, context = self.identify(body)
        saved = self.load(case)
        if not saved or not saved.get("complete") or saved.get("failure"):
            raise Fault("model", "Complete provider recording is unavailable for this smoke task", 409)
        if step >= len(saved["frames"]):
            raise Fault("model", "Recorded completion sequence is exhausted", 409)
        self.check_history(body, saved, step)
        frame = saved["frames"][step]
        if frame.get("context_sha256") != context and not self.portable_matches(case, saved, step, body):
            raise Fault("model", "Recorded context differs (prompt, tools or tool result)", 409)
        return copy.deepcopy(frame["provider_response"]), saved["model"]

    def portable_matches(self, case, saved, step, body):
        from .recorded_context import NORMALIZER, portable_context_digest
        path = self.root / (case["id"] + ".context.json")
        if not path.exists():
            return False
        try:
            if path.is_symlink():
                raise ValueError("symlink")
            with path.open("rb") as file:
                raw = file.read(MAX_RECORDING + 1)
            if len(raw) > MAX_RECORDING:
                raise ValueError("size")
            sidecar = json.loads(raw)
            original = self.root / (case["id"] + ".json")
            if (sidecar.get("normalizer") != NORMALIZER or sidecar.get("task") != case["id"]
                    or sidecar.get("recording_sha256") != hashlib.sha256(original.read_bytes()).hexdigest()
                    or re.fullmatch("[0-9a-f]{64}", sidecar.get("events_sha256", "")) is None
                    or len(sidecar["contexts"]) != len(saved["frames"])):
                raise ValueError("binding")
            if any(item["original_sha256"] != frame["context_sha256"]
                   for item, frame in zip(sidecar["contexts"], saved["frames"])):
                raise ValueError("original contexts")
            return sidecar["contexts"][step]["portable_sha256"] == portable_context_digest(body["messages"], body["tools"])
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            raise Fault("model", "Invalid recorded context sidecar or changed capture artifact", 409) from None
