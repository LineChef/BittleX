"""`python -m pi_pipeline` -> show the resolved feature set (staged bring-up).

    python -m pi_pipeline                         # uses G2_FEATURES from env/.env
    python -m pi_pipeline "profile:p2-gait"       # ...with an override
    python -m pi_pipeline --profiles              # list the bring-up profiles
"""
from __future__ import annotations

import sys

from .features import DEFAULT_PROFILE, PROFILES, Features, _STAGES


def main() -> None:
    if "--profiles" in sys.argv:
        print("staged bring-up profiles (each = previous + one layer):\n")
        for name, delta in _STAGES:
            add = ", ".join(f"{k}={v}" for k, v in delta.items())
            print(f"  {name:14} + {add}")
        print(f"\ndefault (empty G2_FEATURES) = {DEFAULT_PROFILE} (everything on)")
        return

    spec = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    if spec is None:
        from .config import settings
        spec = getattr(settings, "features_spec", "")

    raw = Features.from_spec(spec)
    resolved, notes = raw.resolve()
    print(f"spec:  {spec or '(empty -> ' + DEFAULT_PROFILE + ')'}\n")
    print(resolved.describe())
    if notes:
        print("\ndependency adjustments:")
        for n in notes:
            print(f"  ! {n}")
    if raw != resolved:
        print("\n(raw spec was adjusted -- see above)")


if __name__ == "__main__":
    main()
