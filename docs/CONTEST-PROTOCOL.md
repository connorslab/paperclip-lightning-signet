# Contest-channel development protocol

## Scope

A fixed three-party shared-balance contract, not a standard Lightning/BOLT channel.
This version implements direct allocations only. Pending HTLCs are explicitly
unsupported; the separate accounting model cannot move funded money.

The signers use the Bitcoin functional-test cryptography. It is unsuitable for
production secrets. Fresh per-instance keys are required; do not reuse a signing
key in a different channel or on a different chain. CSFS verifies a template
message, not a conventional transaction sighash. Conventional fee signatures
and the signet funding transaction use SIGHASH_UNIFIED.

## Transactions

Each state output holds exactly 301,000 test sats. Its two Taproot leaves have a
NUMS internal key, preventing a known-key bypass:

1. **Update:** require nLockTime >= 500,000,000 + current state + 1, then verify
   all three CSFS signatures against the spending transaction's TEMPLATEHASH.
2. **Settle:** require 12-block CSV, then enforce the fixed transaction template
   paying that state's three balances. Their sum is 300,000 sats; the remaining
   1,000 sats is the settlement fee.

State numbers are limited to 0..100,000. Their nLockTime values are timestamps in
the past, not future block heights. A newer update commits to its state number
through nLockTime, so it satisfies an older output's CLTV threshold. An older
or same-number update cannot satisfy a newer output's threshold. This is tested
at the script layer, not merely by checking an application sequence counter.

An update has exactly two inputs: the channel output at index 0, and a separately
signed fee coin at index 1. It creates one new 301,000-sat state output. The entire
fee coin becomes the miner fee. TEMPLATEHASH fixes both input sequences and all
outputs, but omits prevouts; the same authorization can therefore supersede an
older state with a different funding outpoint. There are no zero-fee parents,
ephemeral anchors, annexes, or tapscript conditionals. CSFS messages are 32 bytes.

## Agreement and interrupted rounds

The demonstration gives each participant its own explicit approved proposal.
A signer checks its local manifest, balances and approval, takes a journal lock,
and fsyncs the proposed state before releasing its signature. Signing a different
allocation with the same number is refused. Candidate recovery descriptions must
remain available even when a response or final acknowledgement is lost.

A fully signed candidate is potentially publishable: a missing final acknowledgement
must never be treated as revocation. The demo saves complete signature sets with
all participants before calling a transfer agreed. A partial set cannot publish
an update. The regtest interrupts a later round after two signatures and recovers
the previous fully signed state. This is not a proof of a production distributed
agreement protocol; admission, authenticated transport and malicious proposal
handling remain future work.

## Unilateral recovery

An observer sees an old state confirmed, loads the newest signed state and its
own fee coin, and broadcasts an override without requesting channel signatures.
Each confirmed override starts a fresh 12-block settlement delay. The latest
allocation is eventually paid by a signature-free covenant settlement.

This is **contest-based safety**, not permanent revocation. If all honest observers
remain offline through the delay, or cannot get an override confirmed, stale
settlement can win. A mempool transaction alone is not protection. Reorgs can
remove confirmations and restart delays. The test exercises a shallow maturity
reorg; deep reorgs, pinning and adversarial congestion remain unproven.

The opening allocation is state 0 with the same contest semantics. Recovery
information is saved before funding. Participants who never agree an update
can recover state 0 after its delay.

## Fees and limits

Fee inputs preserve channel balances while permitting higher-fee replacement or
rebinding. The demo uses 1,000 and 2,000 sats. The final settlement has a fixed
1,000-sat fee and has no integrated CPFP manager. Fee pressure, adequate reserves,
replacement policy and watchtower response need more testing before any pilot.
The protocol cannot guarantee liveness against censorship or unavailable fee coins.

A participant can force-close the entire group. Membership is fixed, balances
are whole sats with a 1,000-sat minimum, and the channel capacity is fixed in code.
The public demo uses one faucet-funded deposit, not an atomic three-party funding
ceremony. The three payout keys and signing processes are distinct but share a
single administrative host. Do not describe this as a deployed multiparty CLN node.

## Sources

The digest and signature primitives follow [BIP446](https://bips.dev/446/) and
[BIP348](https://bips.dev/348/). The timestamp/contest construction here is an
experimental application of rebindable updates, not a newly standardized BOLT
protocol or an independently audited security result. The original architecture
and related multiparty-channel references remain in DESIGN.md.
