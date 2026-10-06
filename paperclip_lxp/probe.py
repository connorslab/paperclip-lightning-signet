"""Read-only signet probe. Does not start nodes, create wallets or broadcast."""
import argparse
import json
import subprocess
from .network import validate_backend


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bitcoin-cli', required=True)
    parser.add_argument('--datadir', required=True, help='Existing dedicated signet data directory')
    args = parser.parse_args()
    def rpc(*arguments):
        result = subprocess.run([args.bitcoin_cli, f'-datadir={args.datadir}', '-signet', *arguments],
                                capture_output=True, text=True, check=True, timeout=30)
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return result.stdout.strip()
    info = rpc('getblockchaininfo')
    if info.get('chain') != 'signet':
        raise ValueError('refusing a non-signet backend')
    identifier = validate_backend(info, rpc('getblockhash', '0'),
                                  rpc('getblocktemplate', '{"rules":["segwit","signet","blake2b"]}'))
    print(json.dumps({'backend_identity_verified': True, 'network_id': identifier,
                      'lightning_ready': False, 'reason': 'channel implementation is incomplete'}))


if __name__ == '__main__':
    main()
