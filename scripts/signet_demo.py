"""Resumable, explicitly invoked public-signet demonstration; no service restarts.

RPC command is a JSON argument array in --rpc-command. Runtime holds secrets and
MUST stay outside the repository. Each action is one supervised invocation.
"""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from decimal import Decimal
import fcntl

from paperclip_lxp.channel import *
from paperclip_lxp.network import CHALLENGE, GENESIS
from test_framework.segwit_addr import encode_segwit_address
from test_framework.key import ECKey
from test_framework.messages import tx_from_hex
from test_framework.script import sign_input_unified
from test_framework.script_util import key_to_p2wpkh_script, key_to_p2pkh_script

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('action', choices=['prepare', 'resume-funding', 'agree', 'stale', 'override', 'recover', 'close', 'status'])
p.add_argument('--runtime', type=Path, required=True)
p.add_argument('--rpc-command', required=True, help='JSON array invoking bitcoin-cli on an existing signet')
p.add_argument('--funding-wallet', default='faucet')
a = p.parse_args()
repository = Path(__file__).resolve().parents[1]
if a.runtime.resolve() == repository or repository in a.runtime.resolve().parents:
    p.error('private runtime must be outside this repository')
a.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
os.chmod(a.runtime, 0o700)
lock = (a.runtime / 'lock').open('a')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
rpc_command = json.loads(a.rpc_command)


def rpc(method, *params, wallet=None):
    args = rpc_command + (['-rpcwallet=' + wallet] if wallet else []) + [method]
    args += [v if isinstance(v, str) else json.dumps(v) for v in params]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(method + ': ' + result.stderr.strip())
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout.strip() or None


info = rpc('getblockchaininfo')
if (info['chain'] != 'signet' or info.get('signet_challenge') != CHALLENGE or
    rpc('getblockhash', 0) != GENESIS or info['initialblockdownload'] or info['blocks'] != info['headers']):
    raise RuntimeError('wrong or unsynchronized test chain')
if info['mediantime'] <= BASE + MAX_STATE:
    raise RuntimeError('timestamp state range not final on this chain')
path = a.runtime / 'experiment.json'


def broadcast(tx):
    raw = tx.serialize().hex()
    txid = tx.rehash()
    if rpc('gettxout', txid, 0) is not None or txid in rpc('getrawmempool'):
        return txid
    result = rpc('testmempoolaccept', [raw])[0]
    if not result['allowed']:
        raise RuntimeError(json.dumps(result))
    save(a.runtime / (txid + '.json'), {'raw': raw, 'txid': txid})
    return rpc('sendrawtransaction', raw)


def confirmed(outpoint, include_mempool=True):
    out = rpc('gettxout', *outpoint, include_mempool)
    if not out or out['confirmations'] < 1:
        raise RuntimeError('waiting for confirmed unspent output')
    return out


if a.action == 'prepare':
    if path.exists():
        raise RuntimeError('already prepared; resume using existing state')
    public, payouts = [], []
    for i in range(3):
        d = a.runtime / str(i); d.mkdir(mode=0o700, exist_ok=True)
        key = secrets.token_bytes(32)
        ec = ECKey(); ec.set(key, compressed=True)
        if not ec.is_valid:
            raise RuntimeError('invalid generated key')
        save(d / 'key-backup.json', {'secret': key.hex()})
        (d / 'secret.hex').write_text(key.hex()); os.chmod(d / 'secret.hex', 0o600)
        public.append(compute_xonly_pubkey(key)[0].hex())
        payouts.append(key_to_p2wpkh_script(ec.get_pubkey().get_bytes()).hex())
    m = dict(profile='paperclip-lxp-contest-dev-v1', network='paperclip-signet', instance=secrets.token_hex(32),
             pubkeys=public, payout_scripts=payouts)
    states = [dict(number=0, balances=[100000, 100000, 100000]),
              dict(number=1, balances=[95000, 100000, 105000]),
              dict(number=2, balances=[95000, 103000, 102000])]
    fee_keys, fee_addresses = [], []
    for _ in range(2):
        key = secrets.token_bytes(32); ec = ECKey(); ec.set(key, compressed=True)
        fee_keys.append(key.hex())
        fee_addresses.append(encode_segwit_address('tb', 0, key_to_p2wpkh_script(ec.get_pubkey().get_bytes())[2:]))
    save(a.runtime / 'fee-keys.json', fee_keys)
    outputs = [{encode_segwit_address('tb', 1, tree(m, states[0]).output_pubkey): '0.00301000'},
               {fee_addresses[0]: '0.00001000'}, {fee_addresses[1]: '0.00002000'}]
    psbt = rpc('walletcreatefundedpsbt', [], outputs, 0,
               {'fee_rate': 1, 'minconf': 1, 'changePosition': 3}, wallet=a.funding_wallet)
    if Decimal(str(psbt['fee'])) > Decimal('0.0001'):
        raise RuntimeError('funding fee exceeds test budget')
    processed = rpc('walletprocesspsbt', psbt['psbt'], {'sighashtype': 'ALL|UNIFIED'}, wallet=a.funding_wallet)
    finalized = rpc('finalizepsbt', processed['psbt'])
    if not finalized['complete']:
        raise RuntimeError('funding signatures incomplete')
    funding = tx_from_hex(finalized['hex'])
    if funding.vout[0].scriptPubKey != tree(m, states[0]).scriptPubKey or funding.vout[0].nValue != CAPACITY:
        raise RuntimeError('wrong funding output')
    fid = funding.rehash()
    data = dict(manifest=m, states=states, funding=fid, funding_height=None, transactions={},
                funding_fee_sats=int(Decimal(str(psbt['fee'])) * 100000000))
    for i in range(3):
        d = a.runtime / str(i)
        save(d / 'manifest.json', m)
        save(d / 'opening.json', {'state': states[0], 'outpoint': [fid, 0],
                                  'raw_exit': bind_settlement(m, states[0], (fid, 0)).serialize().hex()})
    save(a.runtime / 'funding-raw.json', {'raw': finalized['hex']})
    save(path, data)
    broadcast(funding)
    print(json.dumps({'funding': fid, 'status': 'funded; waiting for confirmation'}))
    sys.exit(0)

data = json.loads(path.read_text())
m, states = data['manifest'], data['states']


def discover_confirmed_state():
    """Follow actual confirmed spends, including unknown fee-input txids.

    Rescan from funding every time in this small dev experiment: no cached state
    that can silently survive a reorg. Unknown allocations fail closed.
    """
    funding = rpc('gettransaction', data['funding'], wallet=a.funding_wallet)
    if funding.get('confirmations', 0) < 1:
        raise RuntimeError('funding not confirmed')
    height = rpc('getblockheader', funding['blockhash'])['height']
    outpoint, number = (data['funding'], 0), 0
    scripts = {tree(m, s).scriptPubKey.hex(): s['number'] for s in states}
    for h in range(height, info['blocks'] + 1):
        block = rpc('getblock', rpc('getblockhash', h), 2)
        for tx in block['tx']:
            if not any((v.get('txid'), v.get('vout')) == outpoint for v in tx['vin']):
                continue
            if len(tx['vout']) == 3:
                actual = [(int(Decimal(str(v['value'])) * 100000000), v['scriptPubKey']['hex']) for v in tx['vout']]
                expected = list(zip(states[number]['balances'], m['payout_scripts']))
                if actual != expected:
                    raise RuntimeError('unexpected settlement')
                return None, number, tx['txid']
            script = tx['vout'][0]['scriptPubKey']['hex']
            candidate = scripts.get(script)
            if candidate is None or candidate <= number or len(tx['vout']) != 1 or Decimal(str(tx['vout'][0]['value'])) != Decimal('0.00301'):
                raise RuntimeError('unknown state spend; inspect participant candidate journals')
            outpoint, number = (tx['txid'], 0), candidate
    return outpoint, number, None


discovered = None
if a.action == 'recover':
    if not data.get('agreed'):
        raise RuntimeError('not agreed')
    outpoint, number, closed = discover_confirmed_state()
    if closed:
        print(json.dumps({'status': 'settled', 'txid': closed, 'state': number})); sys.exit(0)
    # Wait only for a latest-state spend. A stale pending close must be contested,
    # not mistaken for safe progress merely because it reached the mempool first.
    if rpc('gettxout', *outpoint) is None:
        safe_pending = False
        for txid in rpc('getrawmempool'):
            tx = rpc('getrawtransaction', txid, True)
            if not any((v.get('txid'), v.get('vout')) == outpoint for v in tx['vin']):
                continue
            latest_update = (len(tx['vout']) == 1 and
                tx['vout'][0]['scriptPubKey']['hex'] == tree(m, states[2]).scriptPubKey.hex() and
                Decimal(str(tx['vout'][0]['value'])) == Decimal('0.00301'))
            actual = [(int(Decimal(str(v['value'])) * 100000000), v['scriptPubKey']['hex']) for v in tx['vout']]
            latest_close = number == 2 and actual == list(zip(states[2]['balances'], m['payout_scripts']))
            safe_pending = latest_update or latest_close
        if safe_pending:
            print(json.dumps({'status': 'waiting for latest-state spend confirmation'})); sys.exit(0)
    discovered = (outpoint, number)
    if number < 2:
        a.action = 'override'
    else:
        if confirmed(outpoint, False)['confirmations'] < DELAY:
            print(json.dumps({'status': 'contest window', 'confirmations': confirmed(outpoint, False)['confirmations']})); sys.exit(0)
        a.action = 'close'
if a.action == 'resume-funding':
    tx = tx_from_hex(json.loads((a.runtime / 'funding-raw.json').read_text())['raw'])
    print(json.dumps({'funding': broadcast(tx)}))
elif a.action == 'agree':
    confirmed((data['funding'], 0))
    for state in states[1:]:
        signatures = []
        for i in range(3):
            d = a.runtime / str(i)
            save(d / 'approved.json', state)
            response = subprocess.run([sys.executable, '-m', 'scripts.participant', '--directory', str(d)],
                input=json.dumps({'manifest': m, 'state': state}), text=True, capture_output=True, check=True)
            signatures.append(json.loads(response.stdout)['signature'])
        record = dict(state=state, signatures=signatures)
        for i in range(3):
            save(a.runtime / str(i) / ('complete-%d.json' % state['number']), record)
    data['agreed'] = True
    save(path, data)
    print(json.dumps({'status': 'two off-chain allocations fully signed and saved by all three participants'}))
elif a.action in ('stale', 'override'):
    if not data.get('agreed'):
        raise RuntimeError('not agreed')
    n = 1 if a.action == 'stale' else 2
    old = states[discovered[1]] if discovered else states[n - 1]
    prev = discovered[0][0] if discovered else data['funding'] if n == 1 else data['transactions']['stale']
    confirmed((prev, 0), include_mempool=discovered is None)
    record = json.loads((a.runtime / '2' / ('complete-%d.json' % n)).read_text())
    tx = bind_update(m, old, record['state'], [bytes.fromhex(s) for s in record['signatures']],
                     (prev, 0), (data['funding'], n))
    key = bytes.fromhex(json.loads((a.runtime / 'fee-keys.json').read_text())[n - 1])
    ec = ECKey(); ec.set(key, compressed=True)
    pub = ec.get_pubkey().get_bytes()
    tx.wit.vtxinwit[1].scriptWitness.stack = [pub]
    sign_input_unified(tx, 1, key_to_p2pkh_script(pub), ec,
                      [CTxOut(CAPACITY, tree(m, old).scriptPubKey), CTxOut(n * 1000, key_to_p2wpkh_script(pub))], witness=True)
    data['transactions'][a.action] = tx.rehash()
    save(path, data)
    print(json.dumps({'txid': broadcast(tx), 'action': a.action}))
elif a.action == 'close':
    number = discovered[1] if discovered else 2 if 'override' in data['transactions'] else 1 if 'stale' in data['transactions'] else 0
    previous = discovered[0][0] if discovered else data['transactions'].get('override', data['transactions'].get('stale', data['funding']))
    out = confirmed((previous, 0))
    if out['confirmations'] < DELAY:
        raise RuntimeError('waiting for 12 confirmations before settlement')
    tx = bind_settlement(m, states[number], (previous, 0))
    data['transactions']['settlement'] = tx.rehash()
    data['settled_state'] = number
    save(path, data)
    print(json.dumps({'txid': broadcast(tx), 'action': 'close'}))
else:
    observations = {}
    for name, txid in {'funding': data['funding'], **data['transactions']}.items():
        out = rpc('gettxout', txid, 0)
        observations[name] = {'txid': txid, 'unspent': out is not None,
                              'confirmations': out['confirmations'] if out else None}
    print(json.dumps({'height': info['blocks'], 'observations': observations}))
