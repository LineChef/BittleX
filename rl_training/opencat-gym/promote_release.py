"""Promote an exported candidate to the next numbered release (user, 2026-10-09: "if the current run beats V4 then promote it as V5 and we will deploy that to the Pi for testing").

    ../../.venv/bin/python promote_release.py --candidate trained/V6cand_ppo.onnx --name V5 --note "layer 1 of the V6 chain"

Copies the candidate and its sidecar to trained/Release_Candidate<name>_ppo.onnx(.json) (never overwrites), points DEFAULT_POLICY in pi_pipeline/gait/residual_policy.py at it, runs the pi_pipeline
tests, and commits and pushes those files by exact path. With --attachment-only (needs --attachment) DEFAULT_POLICY is left alone and the release becomes only that attachment's
saved gait (ARM1 for the arm, 2026-10-24: V7 stays the policy of the head and of no attachment); a sidecar `base_ref` must have its pi_pipeline/gait/<base_ref>_ref.npy. If the tests fail, everything is put back and the exit code is 2. The previous release stays on the Pi as the fallback (rollback = change that one line
and deploy). The deploy watcher / tools/g2_deploy_when_online.sh then ships it; nothing here touches the Pi."""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
POLICY_PY = os.path.join(ROOT, "pi_pipeline", "gait", "residual_policy.py")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--name", required=True, help="release number, e.g. V5")
    ap.add_argument("--note", default="")
    ap.add_argument("--dry-run", action="store_true", help="check everything and print what would happen; change nothing")
    ap.add_argument("--attachment", default=None, help="also save the release as this attachment's current gait (head or arm; pi_pipeline/attachments/gait_profiles.json)")
    ap.add_argument("--payload-profile", default=None, help="the sim payload the candidate was trained on (written into the release sidecar when it has none)")
    ap.add_argument("--attachment-only", action="store_true", help="save the release as --attachment's gait only: DEFAULT_POLICY does not change")
    ap.add_argument("--trim", default=None, help="the foot trim saved with the attachment's gait (e.g. fl=-0.3); default none until measured")
    a = ap.parse_args()
    if a.attachment_only and not a.attachment:
        print("--attachment-only needs --attachment", flush=True)
        return 1
    src = a.candidate if os.path.isabs(a.candidate) else os.path.join(HERE, a.candidate)
    dst = os.path.join(HERE, "trained", f"Release_Candidate{a.name}_ppo.onnx")
    if not os.path.exists(src) or not os.path.exists(src + ".json"):
        print("candidate or its sidecar is missing", flush=True)
        return 1
    if os.path.exists(dst):
        print(f"{dst} exists: refusing to overwrite", flush=True)
        return 1
    side = json.load(open(src + ".json"))
    if "residual_scale_deg" not in side:
        print("sidecar has no residual_scale_deg", flush=True)
        return 1
    if side.get("base_ref") and not os.path.exists(os.path.join(ROOT, "pi_pipeline", "gait", f"{side['base_ref']}_ref.npy")):
        print(f"sidecar base_ref {side['base_ref']!r}: pi_pipeline/gait/{side['base_ref']}_ref.npy is missing (the Pi could not play the base walk)", flush=True)
        return 1
    old = open(POLICY_PY).read()
    new_line = (f'DEFAULT_POLICY = "Release_Candidate{a.name}_ppo.onnx"  # the deployed policy: {a.name} ({a.note}), set {time.strftime("%Y-%m-%d")}; '
                f'the previous release (Release_CandidateV4_ppo.onnx), V3 and V2.1 stay on the Pi as fallbacks; promoting a new one changes this line')
    text, n = re.subn(r'^DEFAULT_POLICY = ".*$', new_line, old, count=1, flags=re.M)
    if n != 1:
        print("could not find the DEFAULT_POLICY line", flush=True)
        return 1
    if a.attachment_only:
        text = old
    if a.dry_run:
        what = f"save it as {a.attachment}'s gait only" if a.attachment_only else f"point DEFAULT_POLICY at {os.path.basename(dst)}"
        print(f"DRY RUN: would copy {src} (+ .json) to {dst}, {what}, run the pi_pipeline tests, then commit and push", flush=True)
        return 0
    shutil.copy(src, dst)
    if a.payload_profile and not side.get("payload_profile"):
        side["payload_profile"] = a.payload_profile                             # the attachment check reads it (pi_pipeline/attachments)
    json.dump(side, open(dst + ".json", "w"), indent=1)
    open(POLICY_PY, "w").write(text)
    profiles_old = None
    if a.attachment:
        sys.path.insert(0, ROOT)
        from pi_pipeline import attachments as att                              # stdlib only, safe in this venv
        profiles_old = open(att.PROFILES_PATH).read()
        att.register(a.attachment, os.path.basename(dst), trim=a.trim, payload_profile=side.get("payload_profile"), note=a.note)
    t = subprocess.run([os.path.join(ROOT, "pi_pipeline", ".venv", "bin", "pytest"), "-q", "-x"], cwd=ROOT, capture_output=True, text=True)
    if t.returncode != 0:
        open(POLICY_PY, "w").write(old)
        if profiles_old is not None:
            open(att.PROFILES_PATH, "w").write(profiles_old)
        os.remove(dst)
        os.remove(dst + ".json")
        print("pi_pipeline tests FAILED, promotion undone:\n" + (t.stdout + t.stderr)[-800:], flush=True)
        return 2
    rel = lambda p: os.path.relpath(p, ROOT)                                    # noqa: E731
    paths = ([] if a.attachment_only else [rel(POLICY_PY)]) + [rel(dst), rel(dst + ".json")] + ([rel(att.PROFILES_PATH)] if a.attachment else [])
    subprocess.run(["git", "add", "-f", *paths], cwd=ROOT, check=True)
    msg = (f"Promote {a.name} as the {a.attachment} attachment's gait ({a.note}); DEFAULT_POLICY unchanged" if a.attachment_only
           else f"Promote {a.name} to the default policy ({a.note}); the previous release stays as the fallback")
    c = subprocess.run(["git", "commit", "-qm", msg], cwd=ROOT, capture_output=True, text=True)
    if c.returncode != 0:
        print("commit failed:\n" + (c.stdout + c.stderr)[-400:], flush=True)
        return 3
    subprocess.run(["git", "push", "-q", "origin", "development"], cwd=ROOT, capture_output=True, text=True)
    print(f"PROMOTED {a.name}: Release_Candidate{a.name}_ppo.onnx is " + (f"the {a.attachment} attachment's gait (DEFAULT_POLICY unchanged)" if a.attachment_only else "the DEFAULT_POLICY")
          + "; committed and pushed; deploy it with tools/g2_deploy_when_online.sh", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
