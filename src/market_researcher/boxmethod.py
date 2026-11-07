"""Box Method: estimated units = reviews x M, gross = units x price."""

from . import config
from .models import BoxEstimate


def estimate(
    reviews: int,
    price: float,
    low: int = config.BOX_LOW,
    mid: int = config.BOX_MID,
    high: int = config.BOX_HIGH,
) -> BoxEstimate:
    units = [reviews * m for m in (low, mid, high)]
    return BoxEstimate(
        units_low=units[0],
        units_mid=units[1],
        units_high=units[2],
        gross_low=units[0] * price,
        gross_mid=units[1] * price,
        gross_high=units[2] * price,
    )
