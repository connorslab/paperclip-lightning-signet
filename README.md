# Paperclip Lightning Exchange Point

Experimental **three-party Bitcoin shared-balance channel** for Paperclip's
covenant signet. This is development software, not a deployed Lightning router
or a wallet for real funds.

The contest-channel prototype supports two off-chain allocation changes and a
unilateral exit to the latest signed allocation. An older state can be published,
but a participant can supersede it during a **12-block contest window**. The
latest payout then waits its own 12-block delay. Participants must monitor the
chain (or delegate monitoring) and keep fee-paying coins available.

**Not yet implemented:** BOLT invoice/routing integration, on-chain HTLCs,
dynamic membership, autonomous production watchtowers, or production key custody.
The original in-memory HTLC model remains a simulation. It must not authorize
funded conditional payments.

## What is implemented

- Three independent signing processes and separate participant journals.
- Durable recovery information before funding and before releasing signatures.
- TEMPLATEHASH + three CSFS signatures authorizing each allocation update.
- Increasing state numbers enforced by CLTV; CSV delays final payouts.
- An external, unified-sighash-signed fee input for each update/override.
- Restart recovery without fresh channel signatures, refusal to sign conflicting
  states, rejection of incomplete signature sets, and reorg/maturity tests.
- A supervised, resumable public-signet demonstration with fresh test keys.

These are three processes on one operator-controlled host, not three independently
administered nodes. The test coordinator explicitly approves the demonstration's
transfers. The experiment does not establish a production trust boundary.

## Run and understand it

- [Protocol, assumptions and limitations](docs/CONTEST-PROTOCOL.md)
- [Test instructions](docs/TESTING.md)
- [Original proposal](docs/DESIGN.md)
- [Initial opening-only report](reports/2026-10-05.md)

```sh
python3 -m unittest discover -s tests -v
python3 -m paperclip_lxp.demo
```

The chain experiments additionally require the Bitcoin node's functional-test
Python modules. See `dependencies.lock.json` for source revisions. The historical
opening-only experiment remains as a regression demonstration of why fixed
opening refunds cannot safely support balance updates.

Development branch: `experiment/lightning-exchange-point`.
All runtime files, keys and RPC credentials must stay outside this repository.
