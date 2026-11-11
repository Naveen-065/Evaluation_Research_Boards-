import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faults import PROTECTED_BLOCK_BITS, ReferenceEdacBackend, bit_error_count, inject_faults


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.block = bytes((index * 17 + 9) & 0xFF for index in range(1024))

    def test_exact_deterministic_ber(self):
        first = inject_faults(self.block, 1.0, 42)
        second = inject_faults(self.block, 1.0, 42)
        self.assertEqual(first.injected_bits, 82)
        self.assertEqual(first.bit_positions, second.bit_positions)
        self.assertEqual(bit_error_count(self.block, first.corrupted), 82)
        self.assertAlmostEqual(first.actual_percent, 82 * 100 / PROTECTED_BLOCK_BITS)

    def test_reference_backend_is_transparently_single_bit(self):
        backend = ReferenceEdacBackend()
        one = inject_faults(self.block, 100 / PROTECTED_BLOCK_BITS, 7)
        self.assertEqual(backend.process(self.block, one).outcome, "corrected")
        two = inject_faults(self.block, 200 / PROTECTED_BLOCK_BITS, 7)
        result = backend.process(self.block, two)
        self.assertEqual(result.outcome, "detected-uncorrectable")
        self.assertEqual(result.residual_bits, 2)

    def test_invalid_fault_parameters(self):
        for percent in (-1, 101):
            with self.assertRaises(ValueError):
                inject_faults(self.block, percent, 1)
        with self.assertRaises(ValueError):
            inject_faults(b"short", 1, 1)


if __name__ == "__main__":
    unittest.main()
