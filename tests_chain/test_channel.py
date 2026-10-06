import copy
import json
from pathlib import Path
import tempfile
import unittest

from paperclip_lxp.channel import *


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.keys = [(100 + i).to_bytes(32, 'big') for i in range(3)]
        self.m = dict(profile='paperclip-lxp-contest-dev-v1', network='private-regtest',
            instance='a1' * 32, pubkeys=[compute_xonly_pubkey(k)[0].hex() for k in self.keys],
            payout_scripts=['0014' + ('%02x' % (i + 1)) * 20 for i in range(3)])
        self.old = dict(number=0, balances=[100000, 100000, 100000])
        self.new = dict(number=1, balances=[95000, 100000, 105000])
        self.signatures = [sign_schnorr(k, template_hash(update(self.m, self.new))) for k in self.keys]

    def test_signature_binding_and_rebinding(self):
        tx = bind_update(self.m, self.old, self.new, self.signatures, ('11' * 32, 0), ('22' * 32, 1))
        self.assertEqual(template_hash(tx), template_hash(update(self.m, self.new)))
        for change in ('output', 'locktime', 'sequence'):
            bad = copy.deepcopy(tx)
            if change == 'output': bad.vout[0].nValue -= 1
            if change == 'locktime': bad.nLockTime += 1
            if change == 'sequence': bad.vin[1].nSequence -= 1
            self.assertFalse(verify_schnorr(bytes.fromhex(self.m['pubkeys'][0]), self.signatures[0], template_hash(bad)))

    def test_authorization_and_state_bounds(self):
        for sigs in (self.signatures[:2], [self.signatures[0]] * 3):
            with self.assertRaises(ValueError):
                bind_update(self.m, self.old, self.new, sigs, ('11' * 32, 0), ('22' * 32, 1))
        for state in (dict(number=True, balances=[100000] * 3),
                      dict(number=MAX_STATE + 1, balances=[100000] * 3),
                      dict(number=1, balances=[99999, 100000, 100000]),
                      dict(number=1, balances=[100000] * 3, pending=[])):
            with self.assertRaises(ValueError):
                update(self.m, state)
        with self.assertRaises(ValueError):
            bind_update(self.m, self.new, self.new, self.signatures, ('11' * 32, 0), ('22' * 32, 1))

    def test_manifest_and_roster(self):
        for change in ('network', 'pubkeys', 'payout_scripts'):
            bad = copy.deepcopy(self.m)
            if change == 'network': bad[change] = 'mainnet'
            if change == 'pubkeys': bad[change] = [self.m['pubkeys'][0]] * 3
            if change == 'payout_scripts': bad[change][0] = '51'
            with self.assertRaises(ValueError):
                tree(bad, self.old)

    def test_restart_idempotency_and_equivocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / 'secret.hex').write_text(self.keys[0].hex())
            save(d / 'manifest.json', self.m)
            save(d / 'approved.json', self.new)
            sig = participant_sign(d, self.m, self.new)
            self.assertEqual(sig, participant_sign(d, self.m, self.new))
            self.assertEqual(json.loads((d / 'journal.json').read_text())['candidates']['1'], self.new)
            bad = dict(number=1, balances=[94000, 101000, 105000])
            save(d / 'approved.json', bad)
            with self.assertRaisesRegex(ValueError, 'equivocation'):
                participant_sign(d, self.m, bad)
            wrong = copy.deepcopy(self.m); wrong['instance'] = 'b1' * 32
            with self.assertRaisesRegex(ValueError, 'manifest'):
                participant_sign(d, wrong, bad)

    def test_exit_template_is_fixed_and_delayed(self):
        tx = bind_settlement(self.m, self.new, ('11' * 32, 0))
        self.assertEqual(tx.vin[0].nSequence, DELAY)
        self.assertEqual(sum(v.nValue for v in tx.vout), PAYOUT_TOTAL)
        self.assertEqual(len(tx.wit.vtxinwit[0].scriptWitness.stack), 2)
        self.assertEqual(template_hash(tx), template_hash(settlement(self.m, self.new)))


if __name__ == '__main__':
    unittest.main()
