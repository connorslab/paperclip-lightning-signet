"""Immutable proposal accounting. Sequence numbers here are NOT enforced on-chain."""
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import re


def uint(value, name, *, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise ValueError(f'{name} must be a nonnegative integer' if not positive else f'{name} must be a positive integer')


def digest_hex(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise ValueError('expected a lowercase 32-byte hex digest')


@dataclass(frozen=True)
class HTLC:
    id: str
    sender: str
    receiver: str
    amount_msat: int
    payment_hash: str
    expiry_height: int


@dataclass(frozen=True)
class State:
    network_id: str
    instance_id: str
    sequence: int
    balances: tuple[tuple[str, int], ...]
    fee_reserve_msat: int
    capacity_msat: int
    pending: tuple[HTLC, ...] = ()

    def __post_init__(self):
        digest_hex(self.network_id)
        digest_hex(self.instance_id)
        uint(self.sequence, 'sequence')
        uint(self.fee_reserve_msat, 'reserve')
        uint(self.capacity_msat, 'capacity', positive=True)
        members = dict(self.balances)
        if not 3 <= len(members) <= 16 or len(members) != len(self.balances):
            raise ValueError('require 3 to 16 distinct members')
        if self.balances != tuple(sorted(self.balances)):
            raise ValueError('members must be canonically sorted')
        for member, balance in self.balances:
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', member):
                raise ValueError('invalid member ID')
            uint(balance, 'balance')
        if len(self.pending) > 64 or len({h.id for h in self.pending}) != len(self.pending):
            raise ValueError('invalid pending HTLC set')
        for h in self.pending:
            digest_hex(h.id)
            digest_hex(h.payment_hash)
            uint(h.amount_msat, 'HTLC amount', positive=True)
            uint(h.expiry_height, 'expiry', positive=True)
            if h.sender not in members or h.receiver not in members or h.sender == h.receiver:
                raise ValueError('invalid HTLC endpoints')
        if sum(members.values()) + self.fee_reserve_msat + sum(h.amount_msat for h in self.pending) != self.capacity_msat:
            raise ValueError('value conservation violated')

    @classmethod
    def create(cls, network_id, instance_id, balances, fee_reserve_msat):
        return cls(network_id, instance_id, 0, tuple(sorted(balances.items())),
                   fee_reserve_msat, sum(balances.values()) + fee_reserve_msat)

    def commitment(self):
        # A transcript commitment, not a transaction sighash or CSFS signature.
        data = json.dumps(asdict(self), sort_keys=True, separators=(',', ':')).encode()
        return hashlib.sha256(b'Paperclip/LXP/proposal/v0\x00' + data).digest()

    def offer(self, *, expected_sequence, sender, receiver, amount_msat, payment_hash, expiry_height, current_height):
        uint(expected_sequence, 'expected sequence')
        if expected_sequence != self.sequence:
            raise ValueError('stale proposal sequence')
        uint(current_height, 'height')
        uint(expiry_height, 'expiry', positive=True)
        uint(amount_msat, 'amount', positive=True)
        digest_hex(payment_hash)
        balances = dict(self.balances)
        if sender not in balances or receiver not in balances or sender == receiver:
            raise ValueError('invalid endpoints')
        if expiry_height <= current_height:
            raise ValueError('HTLC already expired')
        if balances[sender] < amount_msat:
            raise ValueError('insufficient available balance')
        fields = [sender, receiver, amount_msat, payment_hash, expiry_height]
        identifier = hashlib.sha256(self.commitment() + json.dumps(fields, separators=(',', ':')).encode()).hexdigest()
        hold = HTLC(identifier, sender, receiver, amount_msat, payment_hash, expiry_height)
        balances[sender] -= amount_msat
        return replace(self, sequence=self.sequence + 1, balances=tuple(sorted(balances.items())), pending=self.pending + (hold,))

    def _resolve(self, identifier, current_height, preimage):
        uint(current_height, 'height')
        h = next((h for h in self.pending if h.id == identifier), None)
        if h is None:
            raise ValueError('unknown or already resolved HTLC')
        if preimage is None:
            if current_height < h.expiry_height:
                raise ValueError('HTLC has not expired')
            recipient = h.sender
        else:
            if type(preimage) is not bytes or len(preimage) != 32:
                raise ValueError('preimage must be 32 bytes')
            if current_height >= h.expiry_height:
                raise ValueError('HTLC expired')
            if hashlib.sha256(preimage).hexdigest() != h.payment_hash:
                raise ValueError('incorrect preimage')
            recipient = h.receiver
        balances = dict(self.balances)
        balances[recipient] += h.amount_msat
        return replace(self, sequence=self.sequence + 1, balances=tuple(sorted(balances.items())),
                       pending=tuple(item for item in self.pending if item.id != identifier))

    def fulfill(self, identifier, preimage, *, current_height):
        return self._resolve(identifier, current_height, preimage)

    def timeout(self, identifier, *, current_height):
        return self._resolve(identifier, current_height, None)

    def latest_state_exit(self):
        raise NotImplementedError('latest-state recovery is not implemented; opening recovery is tested separately')
