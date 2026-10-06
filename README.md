# Paperclip Lightning Exchange Point

Private experimental project for a **Bitcoin signet Lightning exchange point
(LXP)**: independent routing nodes share a multi-party channel while retaining
their external two-party Lightning channels.

Active development: `experiment/lightning-exchange-point`.

This is a from-scratch proposal, not an implementation of an established LXP
standard. It is not a deployed Lightning service or a wallet for real funds.
The initial branch contains a shared-balance/conditional-payment model, a
read-only signet backend check, and a three-party covenant-spend experiment.
It does not yet route BOLT payments or invalidate stale signed states. The first
funded experiment includes a timelocked unilateral exit to the opening allocation.
Funded balance updates are blocked until latest-state recovery is proven. A
cooperative spend is not proof of a safe payment channel.

## Working design

Three independent routing nodes start with a shared Bitcoin output. Their
off-chain state tracks each member's balance and conditional transfers. An
optional coordinator proposes updates but must never be able to authorize a
spend alone. External Lightning channels remain owned by their individual
operators. This is not a currency exchange or a channel-opening marketplace.

The test backend is Paperclip's
[Bitcoin covenant signet](https://github.com/connorslab/paperclip-bitcoin-signet),
with TEMPLATEHASH, CSFS and the default **32-byte CSFS message cap**. Default
Knots/RDTS rules remain requirements. No changes to the pool, existing Lightning
services, public signet consensus or production wallets are part of this repo.

## First milestones

1. Test accounting, three-party authorization and unilateral opening-state
   recovery on private regtest, without counterparty signatures at exit time.
2. Extend recovery to the latest state; prove stale-state replacement and crash recovery
   before enabling any funded balance updates.
3. Integrate an isolated Core Lightning adapter with test peers and test invoices.
4. Exercise failure cases on private regtest, then publish test transactions on
   the existing public signet using dedicated test keys and coins.

Public signet deployment is gated on milestone 2. Do not equate passing the
initial primitive tests with a completed multi-party Lightning implementation.

## On the experiment branch

```sh
python -m unittest discover -s tests -v
python -m paperclip_lxp.demo
```

See `docs/DESIGN.md` for the proposed architecture, `docs/TESTING.md` for the
isolated chain test, and `dependencies.lock.json` for the pinned node source.
No credentials, node identities, wallet files or private runtime state belong
in this repository.
