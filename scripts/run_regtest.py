#!/usr/bin/env python3
"""Run only the disposable private-regtest primitive experiment."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--node-source', required=True, type=Path)
parser.add_argument('--tmpdir', required=True, type=Path, help='New disposable directory, never a node/wallet data directory')
parser.add_argument('--results', required=True, type=Path)
parser.add_argument('--experiment', choices=['opening', 'contest'], default='contest')
parser.add_argument('--configfile', type=Path, help='Optional build config for an existing node installation')
args = parser.parse_args()
source = args.node_source.resolve()
root = Path(__file__).resolve().parents[1]
if args.tmpdir.exists():
    parser.error('--tmpdir must not already exist')
if args.results.exists():
    parser.error('--results must not overwrite an existing report')
config = args.configfile.resolve() if args.configfile else source / 'build/test/config.ini'
if not config.is_file():
    parser.error('build the pinned node source before running this experiment')
env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root), str(source / 'test/functional')]),
           LXP_RESULTS=str(args.results.resolve()))
script = 'regtest_contest.py' if args.experiment == 'contest' else 'regtest_three_party.py'
subprocess.run([sys.executable, str(root / 'experiments' / script),
                f'--configfile={config}', f'--tmpdir={args.tmpdir.resolve()}'], env=env, check=True)
