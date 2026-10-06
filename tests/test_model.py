from dataclasses import replace
import hashlib
import unittest
from paperclip_lxp.model import State
from paperclip_lxp.network import CHALLENGE, GENESIS, NETWORK_ID, validate_backend
from paperclip_lxp.funded import FundedUpdatesDisabled, request_funded_update


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.state = State.create(NETWORK_ID, '11' * 32, {'a': 100_000, 'b': 100_000, 'c': 100_000}, 1000)
        self.preimage = b'p' * 32
        self.args = dict(expected_sequence=0, sender='a', receiver='c', amount_msat=20_000,
                         payment_hash=hashlib.sha256(self.preimage).hexdigest(), expiry_height=120, current_height=100)

    def test_fulfill_conserves_value_and_reserve(self):
        pending = self.state.offer(**self.args)
        self.assertEqual(dict(pending.balances)['a'], 80_000)
        done = pending.fulfill(pending.pending[0].id, self.preimage, current_height=110)
        self.assertEqual(dict(done.balances), {'a': 80_000, 'b': 100_000, 'c': 120_000})
        self.assertEqual(done.capacity_msat, self.state.capacity_msat)
        self.assertEqual(done.fee_reserve_msat, 1000)
        self.assertEqual(done.sequence, 2)
        self.assertEqual(len(done.commitment()), 32)
        self.assertEqual(self.state.sequence, 0)

    def test_timeout_restores_sender(self):
        pending = self.state.offer(**self.args)
        with self.assertRaises(ValueError): pending.timeout(pending.pending[0].id, current_height=119)
        done = pending.timeout(pending.pending[0].id, current_height=120)
        self.assertEqual(done.balances, self.state.balances)
        with self.assertRaises(ValueError): pending.fulfill(pending.pending[0].id, self.preimage, current_height=120)

    def test_wrong_preimage_and_double_settlement(self):
        pending = self.state.offer(**self.args)
        for preimage in (b'x' * 32, b'p', 'p' * 32):
            with self.assertRaises(ValueError): pending.fulfill(pending.pending[0].id, preimage, current_height=110)
        done = pending.fulfill(pending.pending[0].id, self.preimage, current_height=110)
        with self.assertRaises(ValueError): done.fulfill(pending.pending[0].id, self.preimage, current_height=110)

    def test_invalid_proposals(self):
        for changes in ({'amount_msat': -1}, {'amount_msat': 0}, {'amount_msat': True},
                        {'amount_msat': 100_001}, {'expected_sequence': 1}, {'receiver': 'a'},
                        {'receiver': 'unknown'}, {'expiry_height': 100}, {'payment_hash': 'invalid'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.state.offer(**(self.args | changes))

    def test_pending_balance_cannot_be_reused(self):
        pending = self.state.offer(**self.args)
        with self.assertRaises(ValueError):
            pending.offer(**(self.args | {'expected_sequence': 1, 'amount_msat': 90_000}))

    def test_context_and_sequence_commitments(self):
        for changed in (replace(self.state, instance_id='22' * 32), replace(self.state, network_id='33' * 32), replace(self.state, sequence=1)):
            self.assertNotEqual(self.state.commitment(), changed.commitment())

    def test_invalid_state_accounting(self):
        for changes in ({'capacity_msat': 1}, {'fee_reserve_msat': -1}, {'sequence': True},
                        {'balances': (('a', 100_000), ('a', 100_000), ('c', 100_000))}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): replace(self.state, **changes)

    def test_latest_state_exit_is_not_confused_with_opening_recovery(self):
        with self.assertRaises(NotImplementedError): self.state.latest_state_exit()

    def test_funded_updates_are_blocked(self):
        with self.assertRaises(FundedUpdatesDisabled): request_funded_update(self.state, self.args)


class BackendTests(unittest.TestCase):
    def test_identity_requires_custom_challenge_not_just_genesis(self):
        info = dict(chain='signet', blocks=100, headers=100, initialblockdownload=False)
        template = dict(signet_challenge=CHALLENGE, rules=['segwit', 'signet', '!blake2b'])
        self.assertEqual(validate_backend(info, GENESIS, template), NETWORK_ID)
        cases = [(info | {'chain': 'main'}, GENESIS, template), (info, '00' * 32, template),
                 (info, GENESIS, template | {'signet_challenge': '51'}),
                 (info, GENESIS, template | {'rules': ['segwit', 'signet']}),
                 (info | {'initialblockdownload': True}, GENESIS, template),
                 (info | {'headers': 101}, GENESIS, template),
                 (info | {'headers': None, 'blocks': None}, GENESIS, template)]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ValueError): validate_backend(*case)
