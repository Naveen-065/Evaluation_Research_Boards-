"""Optional local-Qwen and deterministic demonstration inference runtimes."""

from __future__ import annotations

import os
import re
import hashlib
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class RuntimeInfo:
    kind: str
    available: bool
    label: str
    model_path: str | None
    real_model: bool
    limitation: str

    def public(self) -> dict:
        return asdict(self)


def _chunks(text: str) -> Iterable[str]:
    # Preserve whitespace so streamed chunks concatenate exactly.
    yield from (part for part in re.findall(r"\S+\s*|\s+", text) if part)


class DeterministicDemoRuntime:
    info = RuntimeInfo(
        kind="demo",
        available=True,
        label="Deterministic demo fallback (not Qwen)",
        model_path=None,
        real_model=False,
        limitation="Exercises streaming, BER, EDAC, and FPGA orchestration only; it is not an AI model.",
    )

    def __init__(self):
        self.operation_lock = threading.RLock()
        self._block = hashlib.shake_256(b"Qwen-demo-tensor-view-v1").digest(1024)

    def tensor_info(self) -> dict:
        return {"kind": "synthetic-demo", "name": "demo.synthetic_block", "dtype": "uint8",
                "shape": [1024], "device": "host", "offset_bytes": 0, "length_bytes": 1024,
                "real_model_tensor": False}

    def read_tensor_block(self) -> bytes:
        with self.operation_lock:
            return self._block

    def write_tensor_block(self, block: bytes) -> None:
        if len(block) != 1024:
            raise ValueError("tensor block must contain 1024 bytes")
        with self.operation_lock:
            self._block = bytes(block)

    def stream(self, prompt: str, max_new_tokens: int, cancel: threading.Event) -> Iterable[str]:
        normalized = " ".join(prompt.split())
        preview = normalized[:180] + ("…" if len(normalized) > 180 else "")
        text = (
            "Demo response — local Qwen is not installed on this PC. "
            f"The request was: “{preview}”. "
            "The realtime pipeline, protected 1 KiB block, EDAC decision, and optional ZCU106 probe "
            "are active. Install a local Qwen model and Transformers to replace this deterministic fallback."
        )
        with self.operation_lock:
            for index, chunk in enumerate(_chunks(text)):
                if cancel.is_set() or index >= max_new_tokens:
                    break
                yield chunk


class TransformersQwenRuntime:
    """Lazy, local-files-only Transformers runtime.

    Import and model loading happen only when a request selects the runtime.
    This project never downloads a model implicitly.
    """

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.info = RuntimeInfo(
            kind="qwen-local",
            available=True,
            label=f"Local Qwen · {model_path.name}",
            model_path=str(model_path),
            real_model=True,
            limitation=("BER mutates exactly one 1 KiB view of a live in-memory model tensor. "
                        "The on-disk model is never modified."),
        )
        self._lock = threading.Lock()
        self.operation_lock = threading.RLock()
        self._tokenizer = None
        self._model = None
        self._tensor_name = None
        self._tensor = None

    def _load(self):
        with self._lock:
            if self._model is not None:
                return
            from transformers import AutoModelForCausalLM, AutoTokenizer  # type: ignore
            self._tokenizer = AutoTokenizer.from_pretrained(str(self.model_path), local_files_only=True)
            self._model = AutoModelForCausalLM.from_pretrained(
                str(self.model_path), local_files_only=True, device_map="auto", dtype="auto")

    def _select_tensor(self):
        self._load()
        if self._tensor is not None:
            return self._tensor_name, self._tensor
        for name, parameter in self._model.named_parameters():
            # Accelerate can leave offloaded placeholders on the meta device;
            # those tensors have shape metadata but no readable storage.
            if (getattr(parameter.device, "type", str(parameter.device)) != "meta" and
                    parameter.numel() * parameter.element_size() >= 1024 and
                    parameter.is_contiguous()):
                self._tensor_name, self._tensor = name, parameter
                return name, parameter
        raise RuntimeError("loaded Qwen model has no contiguous tensor large enough for a 1 KiB view")

    def tensor_info(self) -> dict:
        with self.operation_lock:
            name, tensor = self._select_tensor()
            return {"kind": "qwen-live-tensor", "name": name, "dtype": str(tensor.dtype),
                    "shape": list(tensor.shape), "device": str(tensor.device),
                    "offset_bytes": 0, "length_bytes": 1024, "real_model_tensor": True}

    def read_tensor_block(self) -> bytes:
        with self.operation_lock:
            _, tensor = self._select_tensor()
            raw = tensor.detach().view(__import__("torch").uint8).reshape(-1)[:1024].to("cpu")
            return bytes(raw.tolist())

    def write_tensor_block(self, block: bytes) -> None:
        if len(block) != 1024:
            raise ValueError("tensor block must contain 1024 bytes")
        with self.operation_lock:
            import torch
            _, tensor = self._select_tensor()
            raw = tensor.data.view(torch.uint8).reshape(-1)
            source = torch.tensor(list(block), dtype=torch.uint8, device=raw.device)
            with torch.no_grad():
                raw[:1024].copy_(source)
            if tensor.device.type == "cuda":
                torch.cuda.synchronize(tensor.device)

    def stream(self, prompt: str, max_new_tokens: int, cancel: threading.Event) -> Iterable[str]:
        if cancel.is_set():
            return
        with self.operation_lock:
            self._load()
            from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer  # type: ignore
            tokenizer, model = self._tokenizer, self._model
            messages = [{"role": "user", "content": prompt}]
            # Qwen3 defaults to a long thinking trace.  Disable that trace for
            # this realtime control UI; retain compatibility with older Qwen
            # tokenizers that do not expose the template flag.
            try:
                rendered = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                    enable_thinking=False)
            except TypeError:
                rendered = tokenizer.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
            inputs = tokenizer([rendered], return_tensors="pt").to(model.device)
            streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

            class CancelRequested(StoppingCriteria):
                def __call__(self, _input_ids, _scores, **_kwargs) -> bool:
                    return cancel.is_set()

            kwargs = dict(**inputs, streamer=streamer, max_new_tokens=max_new_tokens,
                          do_sample=False,
                          stopping_criteria=StoppingCriteriaList([CancelRequested()]))
            failure = []

            def generate() -> None:
                try:
                    model.generate(**kwargs)
                except Exception as exc:  # surfaced in the request thread below
                    failure.append(exc)
                    streamer.end()

            thread = threading.Thread(target=generate, daemon=True)
            thread.start()
            for text in streamer:
                # Keep the live tensor lock until generate has actually stopped.
                # On cancellation we drain the streamer without exposing more
                # tokens; otherwise a fault injection could race model.generate.
                if not cancel.is_set():
                    yield text
            thread.join()
            if failure:
                raise RuntimeError(f"local Qwen generation failed: {failure[0]}") from failure[0]


def discover_runtime() -> DeterministicDemoRuntime | TransformersQwenRuntime:
    model_value = os.environ.get("QWEN_MODEL_PATH", "").strip()
    if not model_value:
        return DeterministicDemoRuntime()
    model_path = Path(model_value).expanduser().resolve()
    if not model_path.is_dir() or not (model_path / "config.json").is_file():
        return DeterministicDemoRuntime()
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return DeterministicDemoRuntime()
    return TransformersQwenRuntime(model_path)


