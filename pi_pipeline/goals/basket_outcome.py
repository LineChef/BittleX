"""Did the throw go in? (the basket goal, docs/plan-detail/basket-goal-plan.md, step 4.) A pure function of what the finders saw: no camera, no G2, no API.

The basket is a clear shallow tub with red tape on its rim (owner, 2026-11-24). Two kinds of picture read it:
- the look after the throw (about 16 inches, the claw look's three pictures): a puck on the floor outside the tub is a miss; a puck not seen is a QUESTION (NOT_SEEN): inside the tub it is only 0 to 5 coloured pixels at that range, so it cannot be told from an empty tub, and a puck behind the tub or out of the frame looks the same;
- the confirm look (within about 8 inches, the attention pose, the claw at 120, one centred picture): a coloured blob inside the tub's footprint is a make (MADE); nothing inside, and no puck on the floor, is a miss.
A tub (its tape) not in the picture means the look missed it: NO_BASKET, never a make or a miss.
"""
from __future__ import annotations

MADE, MISSED, NOT_SEEN, NO_BASKET = "made", "missed", "not_seen", "no_basket"


def classify_throw(basket, floor_puck=None, tub_puck=None, confirm: bool = False) -> tuple[str, str]:
    """(code, plain words) for one throw. `basket`: the basket finder's reading (or None); `floor_puck`: the puck finder's reading of a puck on the floor outside the tub (or None); `tub_puck`: `puck_finder.find_puck_in_tub_array`'s reading of a puck inside it (or None; only a close picture can see one).
    `confirm` is True for the close confirm look, where nothing seen inside the tub means it is not there."""
    if basket is not None and tub_puck is not None and floor_puck is None:
        return MADE, "The puck is in the basket."
    if basket is not None and tub_puck is not None:
        return MISSED, "Something coloured inside the basket, and a puck on the floor beside it: the puck is outside (seen through the clear wall), not a make."
    if floor_puck is not None:                                                  # a puck seen on the floor is outside the tub, with or without the tub in view
        near = f", about {abs(floor_puck.bearing_deg - basket.bearing_deg):.0f} degrees off its bearing" if basket is not None else ""
        return MISSED, f"The puck is on the floor outside the basket{near}."
    if basket is None:
        return NO_BASKET, "I could not see the basket afterwards, so I cannot say where the throw went."
    if confirm:
        return MISSED, "I looked into the basket from close up and the puck is not there: a miss."
    return NOT_SEEN, "I could not see the puck anywhere: it may be inside the basket or out of my view."
