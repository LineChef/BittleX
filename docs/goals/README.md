---
audience: visitor
kind: overview
---

# Goals: how G2 practises a task and learns from it

A goal is a task G2 practises on his own, with his own camera and IMU to judge the result and no Claude call anywhere in the loop. One spoken command starts a session of up to 10 attempts. After each attempt he scores what happened, decides on the Pi what to change for the next one, and writes it all down. This section explains how that works and shows what the goals have done so far. The operator's side (starting, stopping, pinning a setting, reading the report) is in [Goals: running them](../guides/goals.md).

The goals today
---------------

- [The ball punt](ball-punt.md): G2 finds a green ball on the floor, walks up to it, lines the claw up and punches it, then watches where it went. The goal with the most history.
- [The basket](basket.md): G2 picks up a puck, throws it into a clear tub 16 inches away, and works out whether it went in. The newest goal, and the one still changing.
- Turn away from walls: a standing goal that is always on. Every exploration and ball chase that meets a wall adjusts how close he lets himself get.
- Identify new objects: G2 explores and takes survey pictures of things that match no named object.

The last two are described in [Goals: running them](../guides/goals.md); the charts here cover the first two.

One session
-----------

1. The operator starts it ("G2, ball goal", "G2, basket goal") and G2 says so. It runs inside the running voice service and borrows its serial link, camera and IMU stream.
2. Before every attempt the pack is read; below 30% no attempt starts.
3. G2 makes the attempt using the current value of each setting. Everything he does is the same behaviour code the rest of G2 uses: the goal only chooses numbers.
4. The attempt is scored from what the camera and IMU saw: an outcome code (why it ended), a score from 0 to 1 and whether it counts as a success.
5. The judge records the result against the settings that were used, then picks the next values to try.
6. After 10 attempts, 20 minutes, a pack under 30%, a fall or a stop word the session ends. G2 rests, and some goals end early for a reason of their own (the basket ends on a make).

Scoring
-------

Every attempt gets three things: an outcome code, a score and a success flag. The code says how it ended ("made", "puck not found", "never found"). The score is 1 for a success and a part-credit between 0 and 1 for getting partway, so a goal that is hard to finish still shows progress. The scoring rules are kept in code and change over time; every attempt is stamped with the scoring epoch it was scored under, and attempts from an older epoch are not mixed into what he learns. The charts therefore start a new line where the epoch changes.

How he learns
-------------

- Every setting that can change has its own record: each value tried, how often it worked, and which way the misses pointed.
- He works on one setting at a time, chosen from where the failures point, and changes it by at most one step (Thompson sampling over the records).
- A value only wins with a good record behind it, so one lucky attempt cannot set a number.
- Records are kept per attachment, floor and hardware epoch, so a change of floor starts from his best elsewhere and with fresh evidence.
- Some settings are the operator's: he may only suggest a change, and says so in words when the voice service comes back.
- Nothing here calls the Claude API.

Reading the charts
------------------

Each goal page shows five charts drawn from the goal journal on the Pi, copied to the Mac when the operator syncs. Their numbers are counts of attempts, so the sessions with only a few attempts mean little on their own.

- Success by session: the share of attempts that succeeded in each session, newest on the right.
- Score of every attempt: each attempt's score with a running average. A dashed line is a change of scoring rule.
- How attempts ended: the count of each outcome code.
- Success by setting: the success rate for each value of the goal's main setting, with how many attempts used it.
- Time per attempt: the median seconds an attempt took in each session.

The charts are redrawn every time the operator presses the review page's sync button; the date on the data is in each chart's description. A chart that says there is not enough data yet will fill in as sessions are added.
