"""Single-request, explicitly approved development signer; no network listener."""
import argparse
import json
import sys
from paperclip_lxp.channel import participant_sign

p = argparse.ArgumentParser()
p.add_argument('--directory', required=True)
args = p.parse_args()
request = json.load(sys.stdin)
signature = participant_sign(args.directory, request['manifest'], request['state'])
print(json.dumps({'signature': signature.hex()}))
