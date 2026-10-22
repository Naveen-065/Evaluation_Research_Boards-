"""Software fixtures only; never counted as bench measurements."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from model import validate, plan, MODES, decode_scan, decode_wb, decode_trace

class ModelTests(unittest.TestCase):
    def test_all_modes(self):
        for mode in MODES: self.assertEqual(validate({"mode":mode})["mode"],mode)
    def test_limits(self):
        for data in [{"mode":"exec"},{"row":32},{"col":-1},{"set_v":3.1},{"reset_v":2.29},{"reset_v":3.01},
                     {"set_v":float("nan")},{"reset_v":float("inf")},{"hold":12001},
                     {"hold":0},{"hold":19},{"cycles":11},{"dry_run":"false"},{"shell":"bad"}]:
            with self.assertRaises(ValueError): validate(data)
        self.assertEqual(validate({"hold":20})["hold"],20)
    def test_read_plan_does_not_program(self):
        self.assertEqual(plan(validate({"mode":"array"}))["program_operations"],0)
        self.assertEqual(plan(validate({"mode":"column"}))["cells"],32)
    def test_serial_fpga_mac_validation_and_plan(self):
        p=validate({"mode":"scan_mac","weight_matrix":[[1,0,1],[0,1,0]],
                    "input_vector":[-3,7],"program_matrix":True})
        q=plan(p)
        self.assertEqual(q["matrix_shape"],[2,3])
        self.assertEqual(q["program_operations"],6)
        self.assertEqual(q["fpga_mac_operations"],6)
        self.assertIn("serial",q["array_access"])
        self.assertIn("ZCU106",q["accumulation"])
        for bad in [
            {"weight_matrix":[]},
            {"weight_matrix":[[1],[0,1]],"input_vector":[1,2]},
            {"weight_matrix":[[2]],"input_vector":[1]},
            {"weight_matrix":[[1]],"input_vector":[128]},
            {"weight_matrix":[[1],[0]],"input_vector":[1]},
            {"program_matrix":1},
        ]:
            with self.assertRaises(ValueError): validate({"mode":"scan_mac"}|bad)
    def scan_fixture(self,clip=0):
        a=(1<<9)|(640<<64)|(12000<<80)|(clip<<39)
        b=0x53435232<<224
        for i in range(5):
            a|=(2048*640)<<(96+32*i)
            b|=((2048+i+1)*12000)<<(32*i)
        return f"{a:064X}",f"{b:064X}"
    def test_physical_channel_mapping_and_current(self):
        r=decode_scan(*self.scan_fixture(),0,0,"read",2400)
        self.assertEqual([c["path"] for c in r["channels"][:3]],
                         ["READ / R9","RESET / R11","SET / R10"])
        self.assertAlmostEqual(r["channels"][2]["delta_current_ua"],3/2048/392*1e6)
        with self.assertRaises(ValueError): decode_scan(*self.scan_fixture(),0,1,"read",2400)
    def test_clipped_channel_not_reported_as_current(self):
        r=decode_scan(*self.scan_fixture(2),0,0,"read",2400)
        self.assertIsNone(r["channels"][1]["delta_current_ua"])
        self.assertIsNotNone(r["channels"][0]["delta_current_ua"])
    def test_wb_requires_complete_tagged_bank_and_echo(self):
        packet=0x41F2AA82
        words={i:(f"{(1<<38)|(1<<9):064X}",f"{(0x53435232<<224)|(i<<128)|(packet<<64)|(1<<55)|(0x7fff<<40)|((0x80+i)<<32)|(31<<14)|123:064X}") for i in range(15)}
        r=decode_wb(words,0,31,"read",packet)
        self.assertTrue(r["matching_column"]);self.assertEqual(r["fine"],123)
        with self.assertRaises(ValueError): decode_wb(words,0,31,"read",packet+1)
        words.pop(5)
        with self.assertRaises(ValueError): decode_wb(words,0,31,"read",packet)
    def test_measured_trace_time_order_channels(self):
        word=(6<<56)|(100<<36)|(2051<<24)|(2050<<12)|2049
        raw=(0x54524332<<224)|(100<<209)|(3<<192)|word|(word<<64)|(word<<128)
        count,points=decode_trace(f"{raw:064X}",0,[2048]*3)
        self.assertEqual(count,3)
        self.assertEqual(points[0]["time_us"],10)
        self.assertEqual(points[0]["codes"],[2049,2050,2051])
        self.assertEqual(points[0]["phase"],6)
        with self.assertRaises(ValueError): decode_trace(f"{raw:064X}",3,[2048]*3)

if __name__=="__main__": unittest.main()
