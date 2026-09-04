"""Curiosity -- G2 notices what's new and wants to investigate it.

Channels it drives, all scaled by `level`:
  prompt   -> Claude is told G2 is curious: notices novelty, asks about it, may
              go look.
  bias     -> explore mode triggers sooner and lingers on novel things; strong
              curiosity makes G2 actually approach a new object rather than just
              look; seen things regain their interest faster.
  cues     -> a head-tilt + a rising chirp on spotting something novel; a
              look-around when explore mode starts.
"""
from __future__ import annotations

from .traits import BehaviorParams, Trait


class Curiosity(Trait):
    name = "curiosity"

    def prompt_fragment(self) -> str | None:
        lv = self.level
        if lv < 0.15:
            return None
        if lv < 0.5:
            return ("You are mildly curious -- you notice when something is new "
                    "or out of place and you'll ask about it.")
        if lv < 0.8:
            return ("You are curious. New or unusual things catch your attention "
                    "and you want to know more -- you ask about them, and "
                    "sometimes you go and look for yourself.")
        return ("You are very curious. Novelty pulls at you: a new object, a "
                "sound, a door left open. You point it out, ask about it, and "
                "you like to go investigate on your own.")

    def bias(self, p: BehaviorParams) -> None:
        lv = self.level
        p.idle_secs_before_explore -= 30.0 * lv        # wanders sooner
        p.explore_leg_secs += 2.0 * lv                 # ranges a little further per leg
        p.investigate_secs += 4.0 * lv                 # lingers on a find
        p.novelty_pull += 0.5 * lv                     # strongly drawn to the unseen
        p.revisit_secs -= 90.0 * lv                    # things get interesting again quicker
        p.wander_turn_bias += 0.25 * lv                # covers more directions
        p.vocalize_prob += 0.25 * lv                   # comments on what it finds
        if lv >= 0.6:
            p.approach_novelty = True                  # go up to it, don't just look

    def cues(self, event: str) -> list[str]:
        if self.level < 0.15:
            return []
        if event == "novelty":
            c = ["head_tilt", "chirp_rising"]
            if self.level >= 0.6:
                c.append("approach")
            return c
        if event == "explore_start":
            return ["check_around"]
        return []
