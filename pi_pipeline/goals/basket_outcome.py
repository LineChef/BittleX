"""Did the throw go in? (the basket goal, docs/plan-detail/basket-goal-plan.md, step 4.) A pure function of what the finders saw after the throw: no camera, no G2, no API.

The look afterwards (the active look) gives a picture of the basket's side of the floor. The cylinder seen inside the basket's box is a make; seen on the floor outside it is a miss; not seen at all is unknown, because an opaque
basket hides what is inside and a cylinder out of the frame looks the same (a shallow, light basket removes most of that doubt). A basket that is not in the picture means the look missed it: also unknown, never a make or a miss.
"""
from __future__ import annotations

from ..vision.object_finder import ObjectReading

MADE, MISSED, NOT_SEEN, NO_BASKET = "made", "missed", "not_seen", "no_basket"
INSIDE_MARGIN_PX = 4             # the cylinder's centre may sit this far outside the basket's box and still count as in (the box edge is the colour's edge, not the rim)


def classify_throw(basket: ObjectReading | None, cylinder: ObjectReading | None) -> tuple[str, str]:
    """(code, plain words) for one throw from the finders' readings after it."""
    if basket is None:
        return NO_BASKET, "I could not see the basket afterwards, so I cannot say where the throw went."
    if cylinder is None:
        return NOT_SEEN, "I could not see the cylinder anywhere: it may be inside the basket or out of my view."
    m = INSIDE_MARGIN_PX
    inside = basket.left - m <= cylinder.x <= basket.right + m and basket.top - m <= cylinder.y <= basket.bottom + m
    if inside:
        return MADE, "The cylinder is in the basket."
    return MISSED, f"The cylinder is outside the basket, about {abs(cylinder.bearing_deg - basket.bearing_deg):.0f} degrees off its bearing."
