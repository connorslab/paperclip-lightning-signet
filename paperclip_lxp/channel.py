"""Experimental bounded three-party contest channel. NOT a BOLT channel.

Uses the pinned Bitcoin functional-test primitives (not production crypto).
All signatures authorize templates with fresh, per-channel participant keys.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct

from test_framework.key import H_POINT, compute_xonly_pubkey, sign_schnorr, verify_schnorr
from test_framework.messages import CTransaction, CTxIn, CTxOut, COutPoint, CTxInWitness
from test_framework.script import (CScript, CScriptOp, OP_CHECKLOCKTIMEVERIFY,
    OP_CHECKSEQUENCEVERIFY, OP_DROP, OP_EQUAL, OP_VERIFY, taproot_construct)

BASE = 500_000_000
SEQUENCE = 0xfffffffd
MAX_STATE = 100_000
CAPACITY = 301_000
PAYOUT_TOTAL = 300_000
DELAY = 12
TH = CScriptOp(0xce)
CSFS = CScriptOp(0xcc)


def template_hash(tx):
    tag = hashlib.sha256(b'TemplateHash').digest()
    data = struct.pack('<II', tx.version, tx.nLockTime)
    data += hashlib.sha256(b''.join(struct.pack('<I', i.nSequence) for i in tx.vin)).digest()
    data += hashlib.sha256(b''.join(o.serialize() for o in tx.vout)).digest()
    return hashlib.sha256(tag + tag + data + b'\0' + struct.pack('<I', 0)).digest()


def save(path, value):
    """Atomic durable replacement; caller serializes access to its own journal."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name != 'nt':
        fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def check_manifest(m):
    if m.get('profile') != 'paperclip-lxp-contest-dev-v1':
        raise ValueError('unknown profile')
    if m.get('network') not in ('private-regtest', 'paperclip-signet'):
        raise ValueError('test networks only')
    if len(bytes.fromhex(m['instance'])) != 32:
        raise ValueError('invalid instance')
    if len(m['pubkeys']) != 3 or len(set(m['pubkeys'])) != 3:
        raise ValueError('three distinct keys required')
    if any(len(bytes.fromhex(p)) != 32 for p in m['pubkeys']):
        raise ValueError('xonly keys required')
    # Keep this profile deliberately fixed; no arbitrary scripts or fee changes.
    if len(m['payout_scripts']) != 3:
        raise ValueError('three payout scripts required')
    for script in m['payout_scripts']:
        if len(bytes.fromhex(script)) != 22 or not script.startswith('0014'):
            raise ValueError('P2WPKH payouts required')


def check_state(m, state):
    check_manifest(m)
    if set(state) != {'number', 'balances'}:
        raise ValueError('unknown state fields; pending HTLCs not supported')
    n, balances = state['number'], state['balances']
    if type(n) is not int or not 0 <= n <= MAX_STATE:
        raise ValueError('bounded state number required')
    if len(balances) != 3 or any(type(v) is not int or v < 1000 for v in balances):
        raise ValueError('three non-dust balances required')
    if sum(balances) != PAYOUT_TOTAL:
        raise ValueError('value conservation violated')


def transaction(outputs, sequences, locktime=0):
    tx = CTransaction()
    tx.version = 2
    tx.nLockTime = locktime
    tx.vin = [CTxIn(COutPoint(0, 0), nSequence=seq) for seq in sequences]
    tx.vout = [CTxOut(value, CScript(script)) for value, script in outputs]
    return tx


def settlement(m, state):
    check_state(m, state)
    return transaction(list(zip(state['balances'], map(bytes.fromhex, m['payout_scripts']))), [DELAY])


def tree(m, state):
    check_state(m, state)
    ops = [BASE + state['number'] + 1, OP_CHECKLOCKTIMEVERIFY, OP_DROP]
    for i, pubkey in enumerate(m['pubkeys']):
        ops += [TH, bytes.fromhex(pubkey), CSFS]
        if i < 2:
            ops += [OP_VERIFY]
    recover = CScript([DELAY, OP_CHECKSEQUENCEVERIFY, OP_DROP, TH,
                       template_hash(settlement(m, state)), OP_EQUAL])
    return taproot_construct(bytes.fromhex(H_POINT), [('update', CScript(ops)), ('settle', recover)])


def update(m, state):
    check_state(m, state)
    if state['number'] == 0:
        raise ValueError('opening state is funded directly')
    # Rebindable input 0, separately signed fee input 1. No zero-fee parent.
    return transaction([(CAPACITY, tree(m, state).scriptPubKey)], [SEQUENCE, SEQUENCE], BASE + state['number'])


def witness(tx, tap, leaf, signatures=()):
    tx.wit.vtxinwit = [CTxInWitness() for _ in tx.vin]
    entry = tap.leaves[leaf]
    control = bytes([0xc0 | tap.negflag]) + bytes.fromhex(H_POINT) + entry.merklebranch
    tx.wit.vtxinwit[0].scriptWitness.stack = list(signatures) + [entry.script, control]
    return tx


def bind_update(m, old, new, signatures, outpoint, fee_outpoint):
    if new['number'] <= old['number']:
        raise ValueError('state must increase')
    tx = update(m, new)
    msg = template_hash(tx)
    if len(signatures) != 3 or any(not verify_schnorr(bytes.fromhex(pub), sig, msg)
                                  for pub, sig in zip(m['pubkeys'], signatures)):
        raise ValueError('incomplete or invalid authorization')
    tx.vin[0].prevout = COutPoint(int(outpoint[0], 16), outpoint[1])
    tx.vin[1].prevout = COutPoint(int(fee_outpoint[0], 16), fee_outpoint[1])
    return witness(tx, tree(m, old), 'update', reversed(signatures))


def bind_settlement(m, state, outpoint):
    tx = settlement(m, state)
    tx.vin[0].prevout = COutPoint(int(outpoint[0], 16), outpoint[1])
    return witness(tx, tree(m, state), 'settle')


def participant_sign(directory, manifest, state):
    """One participant per process/directory. Explicit approved proposal required.

    Journal candidate recovery BEFORE returning a signature. A lost response can
    be retried; a different proposal at that sequence is never signed.
    """
    directory = Path(directory)
    with (directory / 'lock').open('a') as lock:
        if os.name == 'nt':
            raise RuntimeError('signer requires Linux advisory locking')
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX)
        own_manifest = json.loads((directory / 'manifest.json').read_text())
        if manifest != own_manifest:
            raise ValueError('manifest mismatch')
        if state != json.loads((directory / 'approved.json').read_text()):
            raise ValueError('proposal not approved by participant')
        check_state(manifest, state)
        path = directory / 'journal.json'
        journal = json.loads(path.read_text()) if path.exists() else {'candidates': {}}
        number = str(state['number'])
        previous = journal['candidates'].get(number)
        if previous is not None and previous != state:
            raise ValueError('equivocation refused')
        if previous is None and state['number'] <= max(map(int, journal['candidates']), default=0):
            raise ValueError('out-of-order proposal refused')
        journal['candidates'][number] = state
        save(path, journal)
        key = bytes.fromhex((directory / 'secret.hex').read_text().strip())
        if compute_xonly_pubkey(key)[0].hex() not in manifest['pubkeys']:
            raise ValueError('key not in roster')
        return sign_schnorr(key, template_hash(update(manifest, state)))
