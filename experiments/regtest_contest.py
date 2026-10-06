#!/usr/bin/env python3
"""Test newer-state overrides, durable signers and fee-funded contest recovery."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys

from paperclip_lxp.channel import *
from test_framework.key import ECKey
from test_framework.script import sign_input_unified
from test_framework.script_util import key_to_p2wpkh_script, key_to_p2pkh_script
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.wallet import MiniWallet


class ContestTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.chain = 'regtest'
        self.setup_clean_chain = True
        self.extra_args = [['-xbtcovtest', '-testactivationheight=blake2b@1', '-rdtsexpiry=2147483647']]

    def run_test(self):
        node = self.nodes[0]
        wallet = MiniWallet(node)
        self.generate(wallet, 105)
        root = Path(self.options.tmpdir) / 'participants'
        keys = [(2011 + i).to_bytes(32, 'big') for i in range(3)]
        payout = []
        for key in keys:
            ec = ECKey(); ec.set(key, compressed=True)
            payout.append(key_to_p2wpkh_script(ec.get_pubkey().get_bytes()).hex())
        m = dict(profile='paperclip-lxp-contest-dev-v1', network='private-regtest',
                 instance=os.urandom(32).hex(), pubkeys=[compute_xonly_pubkey(k)[0].hex() for k in keys],
                 payout_scripts=payout)
        s0 = dict(number=0, balances=[100000, 100000, 100000])
        s1 = dict(number=1, balances=[95000, 100000, 105000])
        s2 = dict(number=2, balances=[95000, 103000, 102000])
        for i, key in enumerate(keys):
            d = root / str(i); d.mkdir(parents=True)
            (d / 'secret.hex').write_text(key.hex()); os.chmod(d / 'secret.hex', 0o600)
            save(d / 'manifest.json', m)
            save(d / 'opening.json', s0)

        def signatures(state):
            sigs = []
            for i in range(3):
                d = root / str(i)
                save(d / 'approved.json', state)
                request = json.dumps(dict(manifest=m, state=state))
                result = subprocess.run([sys.executable, '-m', 'scripts.participant', '--directory', str(d)],
                                        input=request, text=True, capture_output=True, check=True)
                sigs.append(bytes.fromhex(json.loads(result.stdout)['signature']))
            for i in range(3):
                save(root / str(i) / ('complete-%d.json' % state['number']),
                     dict(state=state, signatures=[s.hex() for s in sigs]))
            return sigs

        # Save opening recovery descriptors before exposing any coins.
        funding = wallet.send_to(from_node=node, scriptPubKey=tree(m, s0).scriptPubKey, amount=CAPACITY)
        for i in range(3):
            save(root / str(i) / 'funding.json', funding['txid'])
        sig1, sig2 = signatures(s1), signatures(s2)
        equiv = dict(number=2, balances=[94000, 104000, 102000])
        save(root / '0' / 'approved.json', equiv)
        try:
            participant_sign(root / '0', m, equiv)
            raise AssertionError('equivocation accepted')
        except ValueError as e:
            assert 'equivocation' in str(e)
        partial = dict(number=3, balances=[94000, 104000, 102000])
        partial_sigs = []
        for i in range(2):
            save(root / str(i) / 'approved.json', partial)
            partial_sigs.append(participant_sign(root / str(i), m, partial))
            assert_equal(json.loads((root / str(i) / 'journal.json').read_text())['candidates']['3'], partial)
        try:
            bind_update(m, s2, partial, partial_sigs, ('00' * 32, 0), ('11' * 32, 0))
            raise AssertionError('partial signature set accepted')
        except ValueError:
            pass
        # Fee funds have a real unified-sighash signature, not anyone-can-spend.
        fee_key = ECKey(); fee_key.set((3000).to_bytes(32, 'big'), compressed=True)
        fee_pub = fee_key.get_pubkey().get_bytes()
        fee_script = key_to_p2wpkh_script(fee_pub)
        fees = [wallet.send_to(from_node=node, scriptPubKey=fee_script, amount=v) for v in (1000, 2000, 4000)]
        self.generate(wallet, 1)
        funding_out = (funding['txid'], funding['sent_vout'])

        def signed(old, new, sigs, out, fee, fee_value):
            tx = bind_update(m, old, new, sigs, out, (fee['txid'], fee['sent_vout']))
            tx.wit.vtxinwit[1].scriptWitness.stack = [fee_pub]
            sign_input_unified(tx, 1, key_to_p2pkh_script(fee_pub), fee_key,
                               [CTxOut(CAPACITY, tree(m, old).scriptPubKey), CTxOut(fee_value, fee_script)], witness=True)
            assert_equal(tx.wit.vtxinwit[1].scriptWitness.stack[0][-1], 0x21)
            return tx

        def accepted(tx):
            result = node.testmempoolaccept([tx.serialize().hex()])[0]
            return result['allowed']

        tx1 = signed(s0, s1, sig1, funding_out, fees[0], 1000)
        assert_equal(accepted(tx1), True)
        bad = copy.deepcopy(tx1); bad.wit.vtxinwit[0].scriptWitness.stack[0] = b''
        assert_equal(accepted(bad), False)
        bad = copy.deepcopy(tx1); bad.vout[0].nValue -= 1
        assert_equal(accepted(bad), False)
        txid1 = node.sendrawtransaction(tx1.serialize().hex())
        direct_latest = signed(s0, s2, sig2, funding_out, fees[1], 2000)
        replaced = node.sendrawtransaction(direct_latest.serialize().hex())
        assert replaced in node.getrawmempool()
        assert txid1 not in node.getrawmempool()
        # Reset only this disposable test node's mempool, then test a mined stale state.
        self.restart_node(0, extra_args=self.extra_args[0] + ['-persistmempool=0'])
        assert_equal(node.getrawmempool(), [])
        assert_equal(node.sendrawtransaction(tx1.serialize().hex()), txid1)
        self.generate(wallet, 1)
        old_settle = bind_settlement(m, s1, (txid1, 0))
        assert_equal(accepted(old_settle), False)
        self.restart_node(0)
        # Restore latest complete state from just one participant; no signing keys.
        record = json.loads((root / '2' / 'complete-2.json').read_text())
        for i in range(3):
            (root / str(i) / 'secret.hex').unlink()
        del keys
        tx2 = signed(s1, record['state'], [bytes.fromhex(s) for s in record['signatures']],
                     (txid1, 0), fees[1], 2000)
        assert_equal(accepted(tx2), True)
        # Best-effort late rescue: do not stall merely because a stale close is
        # already in the mempool. This is not a guarantee against it being mined.
        self.generate(wallet, DELAY - 1)
        stale_close_id = node.sendrawtransaction(old_settle.serialize().hex())
        txid2 = node.sendrawtransaction(tx2.serialize().hex())
        assert stale_close_id not in node.getrawmempool()
        block2 = self.generate(wallet, 1)[0]
        # Manually bypass the client guard: consensus CLTV must reject state 1 on state 2.
        stale = update(m, s1)
        stale.vin[0].prevout = COutPoint(int(txid2, 16), 0)
        stale.vin[1].prevout = COutPoint(int(fees[2]['txid'], 16), fees[2]['sent_vout'])
        witness(stale, tree(m, s2), 'update', reversed(sig1))
        stale.wit.vtxinwit[1].scriptWitness.stack = [fee_pub]
        sign_input_unified(stale, 1, key_to_p2pkh_script(fee_pub), fee_key,
                          [CTxOut(CAPACITY, tree(m, s2).scriptPubKey), CTxOut(4000, fee_script)], witness=True)
        assert_equal(accepted(stale), False)
        assert_equal(accepted(old_settle), False)
        latest = bind_settlement(m, s2, (txid2, 0))
        assert_equal(accepted(latest), False)
        self.generate(wallet, DELAY - 2)
        assert_equal(accepted(latest), False)
        self.generate(wallet, 1)
        assert_equal(accepted(latest), True)
        # Reorg below CSV maturity must disable settlement until re-confirmed.
        tip = node.getbestblockhash()
        node.invalidateblock(tip)
        assert_equal(accepted(latest), False)
        node.reconsiderblock(tip)
        assert_equal(accepted(latest), True)
        close = node.sendrawtransaction(latest.serialize().hex())
        self.generate(wallet, 1)
        for i, value in enumerate(s2['balances']):
            assert_equal(int(node.gettxout(close, i)['value'] * 100000000), value)
        result = dict(network='private-regtest', funding=funding['txid'], stale_update=txid1,
                      latest_override=txid2, settlement=close, latest_balances=s2['balances'],
                      restart_recovery=True, no_fresh_channel_signatures=True, stale_state_rejected=True,
                      equivocation_rejected=True, maturity_reorg_test=True, unified_fee_signature=True,
                      interrupted_round_recovery=True, incomplete_signatures_rejected=True,
                      stale_mempool_update_replaced=True,
                      stale_mempool_settlement_replaced=True,
                      contest_blocks=DELAY, payments_are_bolt=False)
        save(os.environ['LXP_RESULTS'], result)


if __name__ == '__main__':
    ContestTest(__file__).main()
