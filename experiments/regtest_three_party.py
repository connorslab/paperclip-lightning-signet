#!/usr/bin/env python3
"""Opening recovery and cooperative primitives; stale signed states remain valid.

Disposable private regtest; fixed keys here must NEVER be used on any public chain.
Uses the pinned Bitcoin node's MIT-licensed functional test framework.
"""
import copy
import json
import os
from pathlib import Path

from feature_bitcoin_covenants import template_hash
from test_framework.key import H_POINT, ECKey, compute_xonly_pubkey, sign_schnorr
from test_framework.messages import COutPoint, CTransaction, CTxIn, CTxInWitness, CTxOut, tx_from_hex
from test_framework.script import CScript, CScriptOp, OP_CHECKSEQUENCEVERIFY, OP_DROP, OP_EQUAL, OP_VERIFY, taproot_construct
from test_framework.script_util import key_to_p2wpkh_script
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import assert_equal
from test_framework.wallet import MiniWallet


class ThreePartyTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.chain = 'regtest'
        self.setup_clean_chain = True
        self.extra_args = [['-btccovtest', '-testactivationheight=blake2b@1', '-rdtsexpiry=2147483647']]

    def run_test(self):
        node = self.nodes[0]
        assert_equal(node.getblockchaininfo()['chain'], 'regtest')
        wallet = MiniWallet(node)
        self.generate(wallet, 105)
        keys = [(1001 + i).to_bytes(32, 'big') for i in range(3)]
        pubkeys = [compute_xonly_pubkey(key)[0] for key in keys]
        ops = []
        for i, pubkey in enumerate(pubkeys):
            ops += [CScriptOp(0xce), pubkey, CScriptOp(0xcc)]
            if i < 2: ops += [OP_VERIFY]
        script = CScript(ops)
        # No participant possesses a known internal private key to bypass 3-of-3.
        internal = bytes.fromhex(H_POINT)
        tx = CTransaction()
        tx.version = 2
        tx.vin = [CTxIn(COutPoint(0, 1), nSequence=0xfffffffd)]
        tx.vout = []
        for key in keys:
            signing_key = ECKey()
            signing_key.set(key, compressed=True)
            tx.vout.append(CTxOut(100_000, key_to_p2wpkh_script(signing_key.get_pubkey().get_bytes())))
        delay = 12
        refund = copy.deepcopy(tx)
        refund.vin[0].nSequence = delay
        refund_script = CScript([delay, OP_CHECKSEQUENCEVERIFY, OP_DROP, CScriptOp(0xce), template_hash(refund), OP_EQUAL])
        tap = taproot_construct(internal, [('cooperative', script), ('refund', refund_script)])
        def fund_with_recovery(name):
            funding = wallet.create_self_transfer(fee_rate=0)['tx']
            assert funding.vout[0].nValue >= 302_000
            funding.vout[0].nValue -= 302_000
            funding.vout.append(CTxOut(301_000, tap.scriptPubKey))
            funding_id = funding.rehash()
            recovery = copy.deepcopy(refund)
            recovery.vin[0].prevout = COutPoint(int(funding_id, 16), 1)
            recovery.wit.vtxinwit = [CTxInWitness()]
            refund_control = bytes([0xc0 | tap.negflag]) + internal + tap.leaves['refund'].merklebranch
            recovery.wit.vtxinwit[0].scriptWitness.stack = [refund_script, refund_control]
            recovery_file = Path(self.options.tmpdir) / (name + '-recovery.json')
            bundle = dict(transaction=recovery.serialize().hex(), funding=funding.serialize().hex())
            with recovery_file.open('x') as stream:
                json.dump(bundle, stream)
                stream.flush()
                os.fsync(stream.fileno())
            directory = os.open(str(recovery_file.parent), os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            assert_equal(json.loads(recovery_file.read_text()), bundle)
            assert_equal(wallet.sendrawtransaction(from_node=node, tx_hex=bundle['funding']), funding_id)
            return dict(txid=funding_id, sent_vout=1), recovery_file

        funded, _ = fund_with_recovery('cooperative')
        self.generate(wallet, 1)
        tx.vin[0].prevout = COutPoint(int(funded['txid'], 16), funded['sent_vout'])
        control = bytes([0xc0 | tap.negflag]) + internal + tap.leaves['cooperative'].merklebranch

        def sign(transaction):
            message = template_hash(transaction)
            assert_equal(len(message), 32)
            transaction.wit.vtxinwit = [CTxInWitness()]
            transaction.wit.vtxinwit[0].scriptWitness.stack = [sign_schnorr(key, message) for key in reversed(keys)] + [script, control]

        def allowed(transaction):
            return node.testmempoolaccept([transaction.serialize().hex()])[0]['allowed']

        sign(tx)
        assert_equal(allowed(tx), True)
        for missing in range(3):
            bad = copy.deepcopy(tx)
            bad.wit.vtxinwit[0].scriptWitness.stack[missing] = b''
            assert_equal(allowed(bad), False)
        bad = copy.deepcopy(tx)
        bad.vout[0].nValue += 1
        bad.vout[1].nValue -= 1
        assert_equal(allowed(bad), False)
        bad = copy.deepcopy(tx)
        bad.wit.vtxinwit[0].scriptWitness.stack[0] = sign_schnorr((9999).to_bytes(32, 'big'), template_hash(tx))
        assert_equal(allowed(bad), False)

        # New fully signed allocation: current opcodes alone DO NOT revoke the old one.
        revised = copy.deepcopy(tx)
        revised.vout[0].nValue -= 5000
        revised.vout[2].nValue += 5000
        sign(revised)
        assert_equal(allowed(revised), True)
        assert_equal(allowed(tx), True)
        self.log.info('KNOWN BLOCKER CONFIRMED: both old and revised fully signed allocations remain valid')
        txid = node.sendrawtransaction(revised.serialize().hex())
        block = self.generate(wallet, 1)[0]
        assert txid in node.getblock(block)['tx']
        for index, value in enumerate((95_000, 100_000, 105_000)):
            output = node.gettxout(txid, index)
            assert_equal(int(output['value'] * 100_000_000), value)

        # A separate opening allocation: nobody signs or cooperates during exit.
        # This is NOT safe to update off-chain: the refund always pays the opening balances.
        exit_funding, recovery_file = fund_with_recovery('opening')
        self.generate(wallet, 1)
        del keys, pubkeys, signing_key
        self.restart_node(0)
        refund = tx_from_hex(json.loads(recovery_file.read_text())['transaction'])
        assert_equal(allowed(refund), False)
        self.generate(wallet, delay - 2)
        assert_equal(allowed(refund), False)
        self.generate(wallet, 1)
        assert_equal(allowed(refund), True)
        tampered = copy.deepcopy(refund)
        tampered.vout[0].nValue += 1
        tampered.vout[1].nValue -= 1
        assert_equal(allowed(tampered), False)
        exit_txid = node.sendrawtransaction(refund.serialize().hex())
        exit_block = self.generate(wallet, 1)[0]
        assert exit_txid in node.getblock(exit_block)['tx']
        for i in range(3):
            assert_equal(int(node.gettxout(exit_txid, i)['value'] * 100_000_000), 100_000)
        self.restart_node(0)
        assert_equal(node.verifychain(), True)
        results = dict(network='private-regtest', participants=3, fee_sats=1000,
                       funding_txid=funded['txid'], settlement_txid=txid, block=block,
                       missing_signatures_rejected=3, wrong_signer_rejected=True, changed_outputs_rejected=True,
                       default_32_byte_cap=True, stale_signed_state_still_valid=True,
                       opening_unilateral_exit=True, unilateral_exit_txid=exit_txid,
                       unilateral_exit_block=exit_block, exit_delay_blocks=delay,
                       recovery_saved_before_funding=True, recovery_after_restart=True, early_exit_rejected=True, altered_exit_outputs_rejected=True,
                       latest_state_exit_implemented=False, funded_updates_enabled=False,
                       lightning_payment_tested=False)
        result_path = os.environ.get('LXP_RESULTS')
        if result_path: Path(result_path).write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    ThreePartyTest(__file__).main()
