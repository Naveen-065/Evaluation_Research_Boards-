import importlib.util
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtimes import TransformersQwenRuntime


class _ParameterShapeOnly:
    def __init__(self, device_type):
        self.device = type("Device", (), {"type": device_type})()

    def numel(self):
        return 4096

    def element_size(self):
        return 2

    def is_contiguous(self):
        return True


class _ShapeModel:
    def named_parameters(self):
        return iter((("offloaded.meta", _ParameterShapeOnly("meta")),
                     ("resident.cpu", _ParameterShapeOnly("cpu"))))


class RuntimeTests(unittest.TestCase):
    def test_tensor_selection_skips_meta_offload_placeholder(self):
        runtime = TransformersQwenRuntime(Path("fixture"))
        runtime._model = _ShapeModel()
        name, tensor = runtime._select_tensor()
        self.assertEqual(name, "resident.cpu")
        self.assertEqual(tensor.device.type, "cpu")

    def test_precancelled_stream_does_not_load_model(self):
        runtime = TransformersQwenRuntime(Path("fixture"))
        cancel = threading.Event(); cancel.set()
        self.assertEqual(list(runtime.stream("ignored", 8, cancel)), [])
        self.assertIsNone(runtime._model)

    @unittest.skipUnless(importlib.util.find_spec("torch"), "PyTorch is optional")
    def test_exact_live_tensor_kib_mutate_and_restore(self):
        import torch

        parameter = torch.nn.Parameter(torch.arange(300, dtype=torch.float32))

        class Model:
            def named_parameters(self):
                return iter((("fixture.weight", parameter),))

        runtime = TransformersQwenRuntime(Path("fixture"))
        runtime._model = Model()
        baseline = runtime.read_tensor_block()
        self.assertEqual(len(baseline), 1024)
        changed = bytearray(baseline); changed[37] ^= 0x20
        runtime.write_tensor_block(bytes(changed))
        self.assertEqual(runtime.read_tensor_block(), bytes(changed))
        runtime.write_tensor_block(baseline)
        self.assertEqual(runtime.read_tensor_block(), baseline)


if __name__ == "__main__":
    unittest.main()
