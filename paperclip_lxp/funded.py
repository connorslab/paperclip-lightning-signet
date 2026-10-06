"""Fail-closed boundary between the proposal model and funded experiments."""


class FundedUpdatesDisabled(RuntimeError):
    pass


def request_funded_update(*args, **kwargs):
    # Opening-state refunds cannot safely back changing off-chain allocations.
    raise FundedUpdatesDisabled('funded updates require verified latest-state unilateral recovery')
