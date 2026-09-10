"""Playfulness -- G2 keeps things light, and would rather engage than sit still.

Deliberately *distinct* from curiosity, not a paler copy:

  curiosity   notices novelty, LINGERS on it, studies it, approaches to inspect.
  playfulness bouncy energy, engages people, punctuates with movement, gets
              bored quickly and flits to the next thing.

The one place they pull against each other is `investigate_secs` -- curiosity
raises it, playfulness lowers it -- so a curious + playful G2 investigates a
thing but not for as long, then does a little wiggle about it.

Channels, all scaled by `level`:
  prompt   -> Claude is told G2 is playful: banter, gentle teasing, small games,
              fidgets/bounces when excited. Still answers what's asked.
  bias     -> comments + fidgets more, zig-zaggier path, shorter dwell on a
              find, less time before it goes looking for something to do; at
              >= 0.5 it walks over to engage rather than only looking.
  cues     -> a play-bow + happy chirp on a greeting, an excited hop for a
              bonded face after an absence, a quick wiggle at novelty.

Note: this trait does NOT touch `caution` -- a "fun" knob shouldn't quietly
lower the obstacle-slowdown threshold.
"""
from __future__ import annotations

from .traits import BehaviorParams, Trait


class Playfulness(Trait):
    name = "playfulness"

    def prompt_fragment(self) -> str | None:
        lv = self.level
        if lv < 0.15:
            return None
        if lv < 0.5:
            return ("You have a playful streak -- a bit of banter, the odd "
                    "teasing aside, and you like punctuating what you say with a "
                    "small movement.")
        if lv < 0.8:
            return ("You are playful. You keep things light, tease gently, "
                    "suggest little games, and you fidget and bounce when you're "
                    "excited -- you'd rather engage than sit still.")
        return ("You are very playful and bouncy. You turn things into a game, "
                "you're quick with a joke or a wiggle, and you get restless when "
                "nothing's happening and go looking for someone to play with. "
                "Still answer what's actually asked -- the play is on top, not "
                "instead of it.")

    def bias(self, p: BehaviorParams) -> None:
        lv = self.level
        if lv < 0.15:
            return
        p.vocalize_prob += 0.30 * lv                 # comments / chirps more
        p.fidget_prob += 0.25 * lv                   # antsy when idle
        p.wander_turn_bias += 0.20 * lv              # zig-zaggy, energetic path
        p.investigate_secs -= 1.5 * lv               # bored of one thing, on to the next
        p.idle_secs_before_explore -= 15.0 * lv      # doesn't sit around
        if lv >= 0.5:
            p.approach_novelty = True                # goes over to engage, not just look

    def cues(self, event: str) -> list[str]:
        lv = self.level
        if lv < 0.15:
            return []
        if event in ("greet", "meet"):
            c = ["play_bow", "chirp_happy"]
            if lv >= 0.5:
                c.append("excited_hop")
            return c
        if event == "recognize":                     # a bonded face after an absence
            return ["excited_hop", "wave"] if lv >= 0.5 else ["wave"]
        if event == "novelty":
            return ["sit_shift", "chirp_happy"] if lv >= 0.6 else ["sit_shift"]
        if event == "explore_start":
            return ["stretch"]
        return []
