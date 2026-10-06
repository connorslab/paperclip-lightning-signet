"""Run an in-memory proposal example; no coins, signatures or node connections."""
import hashlib
import json
from .model import State
from .network import NETWORK_ID


def main():
    preimage = bytes(32)
    state = State.create(NETWORK_ID, '11' * 32, {'alice': 100_000_000, 'bob': 100_000_000, 'carol': 100_000_000}, 1_000_000)
    proposed = state.offer(expected_sequence=0, sender='alice', receiver='carol', amount_msat=5_000_000,
                           payment_hash=hashlib.sha256(preimage).hexdigest(), expiry_height=120, current_height=100)
    settled = proposed.fulfill(proposed.pending[0].id, preimage, current_height=110)
    print(json.dumps({'simulation_only': True, 'balances_msat': dict(settled.balances),
                      'reserve_msat': settled.fee_reserve_msat, 'sequence': settled.sequence,
                      'commitment': settled.commitment().hex()}, indent=2))


if __name__ == '__main__':
    main()
