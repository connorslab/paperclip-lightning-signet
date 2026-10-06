"""Public network constants and a read-only backend identity check."""
import hashlib

GENESIS = '00000008819873e925422c1ff0f99f7cc9bbb232af63a077a480a3633bee1ef6'
CHALLENGE = '2102396d38e3ff703be31a2d97317835f4e9645b5ae5ea2d2d1ba406afa7ab185b5fac'
NETWORK_ID = hashlib.sha256(b'Paperclip/LXP/network/v0\x00' + bytes.fromhex(GENESIS) + bytes.fromhex(CHALLENGE)).hexdigest()


def validate_backend(chain_info, genesis, template):
    if chain_info.get('chain') != 'signet' or genesis != GENESIS:
        raise ValueError('not the expected signet backend')
    # Custom signets share a genesis block. Checking the genesis alone is unsafe.
    if template.get('signet_challenge') != CHALLENGE:
        raise ValueError('wrong custom signet challenge')
    rules = {rule.removeprefix('!') for rule in template.get('rules', [])}
    if 'blake2b' not in rules:
        raise ValueError('backend does not advertise the required proof-of-work rule')
    blocks, headers = chain_info.get('blocks'), chain_info.get('headers')
    if (type(blocks) is not int or type(headers) is not int or blocks < 0 or headers < 0
            or chain_info.get('initialblockdownload') is not False or blocks != headers):
        raise ValueError('backend is not synchronized')
    return NETWORK_ID
