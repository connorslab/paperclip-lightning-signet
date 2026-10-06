# LXP v0: proposed architecture

Historical opening-only design. The newer contest-channel implementation and its
current limitations are described in [CONTEST-PROTOCOL.md](CONTEST-PROTOCOL.md).
The fixed-opening warning below still applies to the original primitive.

Status: original research prototype. No standardized LXP wire protocol is
claimed. Bitcoin/BTC terminology is used throughout.

## Participants and accounting

Start with three independent routing nodes. Each holds its own keys, operates
its own external Lightning channels, and contributes to a shared funding
output. An optional coordinator orders proposals; it is not a custodian and
must not possess the participants' signing keys. Admission is a fixed roster
initially. Dynamic membership requires a separately reviewed protocol.

The proposal model tracks spendable millisatoshi balances, reserved conditional
payments and a distinct on-chain fee reserve. A conditional transfer removes
the amount from the sender immediately. A correct preimage credits the receiver;
expiry refunds the sender. Conservation includes pending amounts and reserves.
These are accounting proposals, not authenticated state commitments or BOLT
payments. The model's expiry convention is not a specification of Bitcoin's
on-chain HTLC race behavior.

## Unilateral recovery is mandatory from the first funding test

The opening output has two Taproot leaves with a NUMS internal key:

- Cooperative leaf: three separate participant signatures over TEMPLATEHASH
  through CSFS, requiring all three signatures.
- Recovery leaf: a 12-block CSV delay followed by a fixed TEMPLATEHASH equality
  check. The committed recovery transaction pays all three opening allocations
  to their respective P2WPKH outputs. Any member can broadcast it alone. No
  coordinator or counterparty signature is required at exit time.

The refund template, scripts, control block, funding outpoint and expected
funding amount must be verified and durably saved before funding. The test
uses exactly 301,000 sats and returns 100,000 sats to each participant with a
1,000-sat fee. These numbers are test parameters, not a fee-estimation policy.
The fixed template cannot increase its fee by changing outputs. CPFP, reserve
management and congestion testing remain required before an operational pilot.

The opening refund is intentionally available to anyone after its delay and
closes the whole group. That creates a force-close/griefing tradeoff. It does
not steal funds: output scripts and amounts are fixed. The delay starts at
funding confirmation, not when a participant requests exit. This is an expiring
opening contract, not a reusable payment channel.

**Do not enable funded balance updates with this opening refund.** It would
restore the opening allocation even after payments. The code blocks funded
updates, while the separate in-memory model allows simulations. Likewise,
signing a new cooperative allocation does not revoke an earlier allocation.
The regtest deliberately confirms that both remain valid to keep this blocker
visible. A locally incremented sequence counter cannot enforce latest-state
settlement on-chain.

## Required work before real LXP transfers

1. Specify the update/contest protocol under the exact available opcodes. Prove
   that a participant with the latest committed state can defeat stale states
   while all other participants and the coordinator are offline.
2. Define signature exchange and partial-round recovery. No participant may lose
   the ability to exit while another holds a usable new allocation. Do not
   hand-wave this as "everyone signs the sequence number."
3. Implement independent durable participant journals and recovery bundles.
   Test crash boundaries, replay, equivocation, aborted rounds and reorgs.
4. Preserve unilateral recovery for pending HTLCs and both external/internal
   payment directions. Set CLTV safety margins from the worst-case exit path
   and fee-bump budget, using blocks rather than assuming one-minute liveness.
5. Connect isolated Core Lightning nodes. A normal CLN channel is two-party;
   a plugin alone cannot make arbitrary multi-party funding safe. Keep BOLT
   invoice handling and external channels conventional; add a reviewed adapter
   for shared-channel lifecycle and conditional routing.
6. Complete unified-sighash integration for all conventional signatures. CSFS
   application signatures are not transaction sighashes and do not themselves
   gain unified-sighash replay protection. The primitive's fixed keys exist
   only on private regtest. Use fresh per-instance keys and explicit transcript
   domain separation in any later signer.

## Signet constraints

The pinned node supports TEMPLATEHASH and CSFS, with a default 32-byte CSFS
message policy. All primitive signature messages are 32-byte template digests.
RDTS prohibits tapscript conditionals and annexes and limits control-block
depth. Do not assume an existing annex-based LN-Symmetry demonstration is
directly compatible or silently relax the signet rules to make it work.

The intended public backend is `node2.paperclippool.xyz`. The signet genesis is
shared with other signets, so matching genesis alone does not identify this
network. The read-only probe also checks the exact challenge, synchronization
and advertised proof-of-work rule. This probe is not a cryptographic proof
against a malicious RPC server, nor a check of every consensus rule.

Before peering, a future adapter must authenticate the participant roster and
bind the exact network/profile and instance to its transcript. Start with
loopback/private test peers and no gossip announcements. Do not invent or reuse
unallocated BOLT feature bits as if they were standardized. Mainnet, existing
CLN data directories and production keys are excluded.

## References and provenance

- [BIP446 TEMPLATEHASH](https://bips.dev/446/) defines the digest used by the
  cooperative and recovery paths; it does not itself order channel states.
- [BIP348 CSFS](https://bips.dev/348/) defines signature verification of stack
  messages. The signet's local 32-byte cap remains in force.
- [Christian Decker's multiparty-channel presentation](https://residency.chaincode.com/presentations/lightning/Multiparty_Channels.pdf)
  provides background on shared balances and state-update mechanisms.
- [Pluggable Channel Factories](https://delvingbitcoin.org/t/pluggable-channel-factories/1252)
  is related adapter research, not the architecture selected for this project.
- [Paperclip Bitcoin signet source](https://github.com/connorslab/paperclip-bitcoin-signet)
  supplies the pinned node and upstream MIT-licensed functional-test utilities.

No third-party factory implementation or CLN source has been copied into this
prototype. The accounting model and test harness are new project code.
