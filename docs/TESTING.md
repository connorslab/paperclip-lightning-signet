# Running the development tests

No mainnet funds, production node directories or production keys are supported.
The scripts never start a mainnet node, trigger IBD or restart an existing service.

## Fast tests

```sh
python3 -m unittest discover -s tests -v
python3 -m paperclip_lxp.demo
PYTHONPATH=.:/path/to/bitcoin/test/functional python3 -m unittest discover -s tests_chain -v
```

The first ten tests cover the original accounting model. The five chain-library
unit tests cover template binding, signer authorization, journals and exit
construction. They do not run consensus validation. GitHub CI runs these two
suites; actual chain results are recorded separately in reports.

## Private regtest

Build the source revision in `dependencies.lock.json`, or use an already-built
compatible experimental node with an explicit functional-test config:

```sh
python3 scripts/run_regtest.py \
  --node-source=/path/to/paperclip-bitcoin-signet \
  --experiment=contest \
  --tmpdir=/tmp/lxp-regtest-new \
  --results=/tmp/lxp-results-new.json
```

`--configfile=/path/to/test/config.ini` overrides the usual build/test/config.ini.
The runner refuses existing result and data paths. This launches one isolated
private-regtest node. It tests:

- Three signing subprocesses with independent journals and explicit approvals.
- Missing signatures, altered outputs, equivocation and an interrupted later round.
- Replacement of a stale update in the mempool using a higher fee input.
- A confirmed stale state, followed by latest-state recovery after restart.
- A stale settlement in the mempool, replaced before confirmation (best effort).
- Consensus rejection of an older update spending a newer state output.
- CSV exit timing, a shallow reorg across maturity, and final output amounts.
- Unified-sighash fee signatures; no fresh participant channel signatures at exit.

`--experiment=opening` runs the historical opening-only regression. Its cooperative
allocation path is deliberately unsafe for updated balances and remains disabled
in the old funded-model API. Use the new contest-channel module for dev experiments.

## Supervised public signet demonstration

Use an existing synchronized Paperclip covenant-signet backend. Genesis alone
is insufficient: the script verifies the exact signet challenge. RPC stays private.
The public signet's historical running binary is recorded separately from the
recommended newer source revision. Neither service upgrades nor policy changes
are performed by this demonstration.

```sh
export PYTHONPATH=.:/path/to/bitcoin/test/functional
RPC='["bitcoin-cli","-datadir=/existing/signet/datadir"]'
RUNTIME=/private/path/outside/this/repository
python3 -m scripts.signet_demo prepare --runtime "$RUNTIME" --rpc-command "$RPC" --funding-wallet faucet
# Wait for the funding transaction to confirm.
python3 -m scripts.signet_demo agree --runtime "$RUNTIME" --rpc-command "$RPC"
python3 -m scripts.signet_demo stale --runtime "$RUNTIME" --rpc-command "$RPC"
# A bounded watcher follows actual confirmed spends and recovers the latest state.
python3 -m scripts.watch --runtime "$RUNTIME" --rpc-command "$RPC" --max-seconds 1800
```

The selected funding wallet must already be loaded and contain spendable test
coins. Preparation uses 304,000 test sats plus a 1 sat/vB funding fee, with a
10,000-sat maximum funding-fee guard. It saves recovery material before broadcasting.
The run uses a single faucet-funded output; it is not a three-party atomic funding
protocol. Two signed allocations change 100,000/100,000/100,000 into
95,000/100,000/105,000, then 95,000/103,000/102,000.

The deliberate stale broadcast is a test action, not normal operation. `recover`
is a single watcher iteration; `status` shows current UTXO observations.
`resume-funding` reuses the prepared funding transaction after an interrupted
broadcast. Do not create a new runtime to retry a run that already has an
experiment.json file. Preserve the private runtime and its participant backups.

The watcher is bounded, uses polling and exits visibly on errors. It rescans from
the funding block to avoid trusting a cached state after reorgs. A production
watchtower, congestion handling, multiple fee reserves and deep-reorg recovery
remain future work. Keep supervising the experiment until its exit is confirmed.
The test leaves payout coins at the three generated participant addresses; their
keys stay in the private runtime. Never publish that directory.

## Scope of evidence

This proves a bounded development shared-balance contract can open, update and
exit on the experimental network. It does not prove BOLT interoperability, pending
HTLC recovery, independent administrative isolation, atomic multi-party funding,
unbounded offline safety, adversarial fee-market liveness or production security.
