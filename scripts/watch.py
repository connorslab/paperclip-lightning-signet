"""Bounded dev watch process. Follows signet_demo's actual on-chain spend path."""
import argparse
import json
import subprocess
import sys
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--runtime', required=True)
p.add_argument('--rpc-command', required=True)
p.add_argument('--funding-wallet', default='faucet')
p.add_argument('--max-seconds', type=int, default=1800)
p.add_argument('--interval', type=int, default=15)
a = p.parse_args()
if not 1 <= a.interval <= 60 or not 1 <= a.max_seconds <= 3600:
    p.error('interval must be 1..60 and maximum runtime 1..3600 seconds')
deadline = time.monotonic() + a.max_seconds
while time.monotonic() < deadline:
    result = subprocess.run([sys.executable, '-m', 'scripts.signet_demo', 'recover',
        '--runtime', a.runtime, '--rpc-command', a.rpc_command, '--funding-wallet', a.funding_wallet],
        text=True, capture_output=True, timeout=60)
    if result.returncode:
        # Fail visibly rather than continuing on unknown spends or missing recovery.
        print(result.stderr, file=sys.stderr, flush=True)
        sys.exit(result.returncode)
    output = json.loads(result.stdout)
    print(json.dumps(output), flush=True)
    if output.get('status') == 'settled':
        sys.exit(0)
    time.sleep(a.interval)
sys.exit('Watch deadline reached; inspect channel and restart monitoring promptly')
