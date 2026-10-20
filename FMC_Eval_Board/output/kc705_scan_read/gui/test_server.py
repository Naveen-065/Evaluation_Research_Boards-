import unittest
from server import decode

def result(row=3,col=5,nb=640,na=12000,base=2048,code=2096):
    a=(1<<9)|(((row<<10)|(col<<5)|row)<<16)|(nb<<64)|(na<<80)
    b=0x53435231<<224
    for i in range(5): a|=base*nb<<(96+32*i); b|=code*na<<(32*i)
    return f'{a:064x}',f'{b:064x}'

class DecoderTests(unittest.TestCase):
    def test_channel_labels_match_pcb_output_routes(self):
        import json
        from pathlib import Path
        pads=json.loads((Path(__file__).resolve().parents[2]/'ain1_r9_validation/current_pcb_pads.json').read_text())
        nets={(p['ref'],p['pad']):p['net'] for p in pads}
        self.assertEqual(nets['R46','1'],'Net-(U13-OUT+)')
        self.assertEqual(nets['R46','2'],'AMP2_P')
        self.assertEqual(nets['R39','1'],'Net-(U11-OUT+)')
        self.assertEqual(nets['R39','2'],'AMP3_P')
        x=decode(*result(),3,5)
        self.assertEqual(x['channels'][1]['path'],'RESET / R11')
        self.assertEqual(x['channels'][2]['path'],'SET / R10')
    def test_real_units_and_cell(self):
        x=decode(*result(),3,5)
        self.assertEqual(x['packet'],'0x0CA3')
        self.assertAlmostEqual(x['channels'][1]['delta_current_ua'],48/2048/7/56*1e6)
        self.assertFalse(x['calibrated'])
    def test_wrong_cell_rejected(self):
        with self.assertRaisesRegex(ValueError,'address'): decode(*result(),0,0)
    def test_missing_samples_rejected(self):
        with self.assertRaisesRegex(ValueError,'window'): decode(*result(na=10),3,5)
    def test_fault_rejected(self):
        a,b=result()
        with self.assertRaisesRegex(ValueError,'successfully'): decode(f'{int(a,16)|(1<<10):x}',b,3,5)
    def test_negative_signed_delta(self):
        x=decode(*result(base=2096,code=2048),3,5)
        self.assertLess(x['channels'][0]['delta_current_ua'],0)
    def test_clipping_flag_preserved(self):
        a,b=result(); x=decode(f'{int(a,16)|(1<<37):x}',b,3,5)
        self.assertTrue(x['clipped'])
    def test_saturated_channel_has_no_current_claim(self):
        x=decode(*result(code=0),3,5)
        self.assertIsNone(x['channels'][1]['estimated_current_ua'])
        self.assertIsNone(x['channels'][1]['delta_current_ua'])

if __name__=='__main__': unittest.main()
