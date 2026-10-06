# Running the initial tests

Only disposable private regtest is authorized by the provided chain runner.
It cannot select mainnet or public signet. It creates a new data directory and
refuses an existing one. It does not touch any existing node or Lightning daemon.

## Model and network guards

```sh
python3 -m unittest discover -s tests -v
python3 -m paperclip_lxp.demo
```

These tests do not connect to a node. They cover conservation, held balances,
preimages, timeouts, duplicate resolution, proposal sequence mismatches,
context-separated commitments, wrong network/challenge rejection, and blocking
funded updates. They do not prove channel cryptography or Lightning routing.

## Real node test

Build the exact node revision from `dependencies.lock.json`. From this repo:

```sh
python3 scripts/run_regtest.py \
  --node-source=/path/to/paperclip-bitcoin-signet \
  --tmpdir=/tmp/paperclip-lxp-regtest-new \
  --results=/tmp/paperclip-lxp-results-new.json
```

The test uses the node's existing functional-test framework, mines disposable
regtest coins, checks three-party authorization, broadcasts a cooperative
settlement, and tests a separate unilateral opening-state exit. The exit is
rebuilt from a recovery file after a node restart and without further signer
calls. It must fail before the delay, reject altered output allocations and
pay all three opening balances after the delay. The test verifies the mined
outputs and restarts/verifies the chain again.

The test also confirms the current limitation: old and revised fully signed
cooperative states are both valid before either spends the funding output.
This is an expected blocker assertion, not a successful latest-state protocol.
There are no participant network daemons yet, so this is proof of recovery
without counterparty signatures, not a full disconnected-peer integration test.

All keys in this harness are deterministic and public test fixtures. Never run
it against an existing funded wallet or reuse these keys on public signet.
The report contains only public regtest transaction IDs and boolean results.

## Read-only public backend check

For an existing dedicated signet node, without starting a node or syncing:

```sh
python3 -m paperclip_lxp.probe \
  --bitcoin-cli=/path/to/bitcoin-cli --datadir=/existing/signet/datadir
```

This only calls getblockchaininfo, getblockhash and getblocktemplate. It does
not fund the experiment, broadcast, create a wallet or attest Lightning readiness.

## Release gate

No public signet LXP funding/peering until latest-state unilateral recovery,
pending-payment recovery, fee pressure, crash/reorg handling and independent
participant signer integration have passed. No production deployment is included.
