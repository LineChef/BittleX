# Attachments: switching what G2 wears on the neck

G2 wears one attachment on the neck at a time: the Petoi AI head, the Petoi robot arm, or nothing beyond the stock head. One setting says which is fitted. Switching it also switches the gait policy saved for that attachment, checks that the BiBoard firmware fits, and adds or removes the attachment's skills. Swaps are expected to be rare, but every one should work with one command. Code: [`pi_pipeline/attachments/`](../../pi_pipeline/attachments/__init__.py).

## Switch

1. Power G2 off and swap the hardware (each attachment's checklist is printed by `g2attach <name>`).
2. For the arm: the BiBoard must run Petoi's **Bittle X+Arm** firmware and the claw must be calibrated (see [Firmware](#firmware)).
3. Power on, then from the Mac:

```bash
g2attach head        # or arm, or none: sets it on the Pi, prints the checklist, restarts the voice loop (g2reset)
g2attach status      # the fitted attachment, the gait it runs and why
g2attach list        # every attachment, the firmware it needs, its saved gaits
```

`g2attach` needs `G2_PI` like the other Pi helpers. On the Pi itself: `python -m pi_pipeline.attachments status | list | use NAME`.

## How the setting is read

In this order: `G2_ATTACHMENT` in the environment (or `.env`), else the state file `~/.local/share/g2/attachment.json` that `g2attach` writes (moved with `G2_ATTACHMENT_FILE`), else `none`. An unknown name logs a warning and counts as `none`.

`none` means no attachment: no firmware question is sent, no attachment skill is added and the head tool server is never imported. (Every attachment, `none` included, also sets the BiBoard's voice module to English at each start-up: `XAc`, a 1.2 s pause, then `XAa`. The profile key `voice_module_language` in `gait_profiles.json` says `english` for each; a missing profile still means English, and `off` turns it off. The module falls back to Chinese after some power cycles; the sequence runs when the voice service or the app starts, not when the board alone is power-cycled.) It has its own saved-gait slot like the others. **While nothing is saved for `none`, it is exactly the behaviour G2 had before attachments existed**: the policy is `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py` and the trim comes from `DEFAULT_TRIMS`. Tests pin this (`pi_pipeline/tests/test_attachments.py`).

## Saved gaits

[`pi_pipeline/attachments/gait_profiles.json`](../../pi_pipeline/attachments/gait_profiles.json) holds, for each of `none`, `head` and `arm`:

| Field | Meaning |
|---|---|
| `payload_profile` | The sim payload the attachment's policies must be trained on (`pod` = the 185 g pod + the 42 g AI head; `none` and the arm get theirs when a policy is trained for them) |
| `current` | The policy in use, its foot trim, the payload it was trained on, the date it was saved |
| `history` | Earlier policies, newest last: the last-known-good when the current one cannot be used |

At start-up the fitted attachment's `current` runs. It is skipped when its file is missing or when its sidecar's `payload_profile` names a different payload; the newest usable history entry runs instead. If nothing saved is usable, the legacy `DEFAULT_POLICY` runs and the reason is logged (`g2attach status` and `python -m pi_pipeline.doctor` show it). A policy without a recorded payload is allowed and flagged. `G2_FOOT_TRIM` still overrides the saved trim.

Saving a gait:

- **Promotion:** `promote_release.py --candidate trained/X.onnx --name V7 --attachment head --payload-profile pod [--trim fl=-0.3]` copies the release, points `DEFAULT_POLICY` at it as before, writes the payload into the release sidecar, and saves it as the attachment's current gait (the previous one moves to the history). It commits the profile file with the release.
- **One attachment only:** add `--attachment-only` to save the release as that attachment's gait without moving `DEFAULT_POLICY` (the arm's ARM1, so V7 stays the head and no-attachment policy). A sidecar `base_ref` must have its `pi_pipeline/gait/<base_ref>_ref.npy` (ARM1: `wkArm_ref.npy`, Petoi's arm walk).
- **By hand:** `g2attach save head Release_Candidate<name>_ppo.onnx --trim fl=-0.3 --payload pod` edits the profile file on the Mac; commit it and deploy.
- **Per floor:** `python -m pi_pipeline.attachments floor-trim tile fl=-0.1` saves a trim measured on one floor for the fitted attachment's current gait (`off` removes it). When the floor label (`g2floor`) is set and under 12 hours old, a walk on that floor uses it; any other floor uses the general trim. The order is `G2_FOOT_TRIM`, then the per-floor trim, then the saved trim, then `DEFAULT_TRIMS`. Floor labels are always set by a person; nothing names the floor automatically.
- **Exports:** a new export records its payload with `export_onnx.py --sidecar-extra '{"payload_profile": "pod"}'`.

`tools/g2_deploy_when_online.sh` sends every policy a saved gait names, as well as `DEFAULT_POLICY`, so a swap never needs a new deploy.

## Firmware

Each attachment names the BiBoard firmware it needs: the first line of the BiBoard's `?` banner. The arm is a separate build of Petoi's firmware (compile-time option `ROBOT_ARM`, model "Bittle X+Arm": its own skill table, the claw on the tail joint, index 2, and a wider range for joint 1). At start-up the voice service and the app ask `?` when an attachment other than `none` is fitted; if the firmware does not fit, they log it and take the attachment's skills out. `python -m pi_pipeline.doctor --serial` shows the same check.

| Attachment | Firmware accepted |
|---|---|
| `none` | not checked |
| `head` | `Bittle X` (the arm build shifts every posture and swaps the gaits, so it is not accepted for the head) |
| `arm` | `Bittle X+Arm` |

The arm's skills (`pick_up`, `put_down`, `toss`, `show_off`, `clap`: tokens `pickF`, `putF`, `tossF`, `showOff`, `clap` from Petoi's arm page, [`../planned/robot-arm.md`](../planned/robot-arm.md)) are offered to the conversation only with the arm fitted, the arm firmware answering and the profile's `skills` switch on. None has been run on G2 yet, so the arm profile has it off until they pass a bench test.

## Behaviour switches

A profile in `gait_profiles.json` can switch Pi behaviour off while its attachment is fitted. A missing key means on, so `none` and `head` behave as before.

| Key | Off means | Arm |
|---|---|---|
| `easing` | no stand-up ramp, no eased move into a skill, no blend to balance at the end of a walk (`G2_STAND_RAMP_S` / `G2_TRANSITION_RAMP_S` are ignored) | off |
| `gyro_balance` | the firmware gyro balance stays off: every `gB` the Pi sends goes out as `gb`, poses no longer turn it on, and start-up sends `gb` | off |
| `gait_switching` | the gait is held at normal; "hi step" or "carpet mode" is answered "Not with the arm fitted" and not obeyed; a carpet floor label does not switch it | off |
| `skills` | the attachment's own skills stay out of the conversation | off |

The arm has all four off for its first hardware round (user, 2026-10-24: [`../plan-detail/arm-policy-plan.md`](../plan-detail/arm-policy-plan.md)). Turning one back on is a one-line profile edit and a deploy.

## Open with the arm fitted (2026-10-24)

1. Done: the calibration was backed up before the reflash and survived it ([`../../blueprints/calibration.md`](../../blueprints/calibration.md)).
2. Decided: the head does not accept the Bittle X+Arm firmware (it shifts every posture and swaps the gaits), so going back to the AI head is a reflash to plain Bittle X with the calibration checked.
3. A no-attachment policy: the sim has no payload profile yet for the pod without the head (185 g); add one, train it with the same recipe and save it for `none` (until then `none` runs the legacy `DEFAULT_POLICY`).
4. Weigh the arm and the camera (the sim's `arm` profile uses Petoi's spec-page estimate, 63 g, and 15 g); ARM1 trained on it: [`../plan-detail/arm-policy-plan.md`](../plan-detail/arm-policy-plan.md).
5. Run the arm's skill tokens on the bench before they are trusted.

## What a setting cannot switch

The flag controls software. The attachment's own hardware is physical: a powered AI head runs its own firmware whatever the Pi does, a reflash changes the BiBoard until the next reflash, and removing the Pi's own microphone and speaker (a later AI-head step) cannot be undone by a setting. Keep the head's transmit line unconnected and the BiBoard's voice module connected unless a decision says otherwise. Head plan: [`../planned/ai-head/README.md`](../planned/ai-head/README.md).
