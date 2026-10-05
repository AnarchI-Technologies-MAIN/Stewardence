"""Current exposure entrypoint and explicit permanent historical dispatch.

Pack v2 identities always use exposure_v1. New semantics require a successor
pack schema and a separately qualified dispatcher, never a current alias swap.
"""

from .exposure_v1 import VERSION as VERSION
from .exposure_v1 import Outcome as Outcome
from .exposure_v1 import ReviewQuestion as ReviewQuestion
from .exposure_v1 import review_record as review_record


def historical_review_record(record, manifest_schema):
    if manifest_schema != "stewardence.review_pack.v2":
        raise ValueError("Unsupported historical exposure pack schema")
    # Deliberately resolve the permanent version, not the current public alias.
    from .exposure_v1 import review_record as historical_v1

    return historical_v1(record)
