"""Export a trained SB3 PPO policy to ONNX for on-Pi (onnxruntime) inference.

Exports ONLY the deterministic action path -- the same thing
`model.predict(obs, deterministic=True)` returns:

    obs(278) -> policy_net[Linear 278x256, Tanh, Linear 256x256, Tanh]
             -> action_net[Linear 256x8]
             -> clip to the action space [-1, 1]

The value network and the log_std (exploration noise) are training-only and are
dropped. There is no VecNormalize on this run (obs come out of the env already
bounded/normalised), so no normalisation stats to bake in -- verified by the
absence of trained/run20m_ppo_vecnormalize.pkl.

    python export_onnx.py --model trained/run20m_ppo --out trained/run20m_ppo.onnx
    python verify_onnx.py --model trained/run20m_ppo --onnx trained/run20m_ppo.onnx   # then check parity
"""
import argparse
import os

import numpy as np
import torch
import torch.nn as nn
from stable_baselines3 import PPO


class DeterministicPolicy(nn.Module):
    """The mean-action forward path of an SB3 continuous PPO policy, plus the
    action-space clip. Weights are copied in from the loaded model."""

    def __init__(self, policy, act_low, act_high):
        super().__init__()
        # SB3 MlpPolicy: features_extractor is FlattenExtractor (identity for a
        # vector obs), so the net is mlp_extractor.policy_net -> action_net.
        self.policy_net = policy.mlp_extractor.policy_net
        self.action_net = policy.action_net
        self.register_buffer("act_low", torch.as_tensor(act_low, dtype=torch.float32))
        self.register_buffer("act_high", torch.as_tensor(act_high, dtype=torch.float32))

    def forward(self, obs):
        x = self.policy_net(obs)
        mean = self.action_net(x)
        return torch.clamp(mean, self.act_low, self.act_high)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--out", default=None, help="default: <model>.onnx")
    ap.add_argument("--opset", type=int, default=13)
    args = ap.parse_args()
    out = args.out or (args.model + ".onnx")

    vn = args.model + "_vecnormalize.pkl"
    if os.path.exists(vn):
        raise SystemExit(f"{vn} exists -- this run DID use VecNormalize; the exporter "
                         "would need to bake in the obs mean/var. Handle that before exporting.")

    model = PPO.load(args.model, device="cpu")
    obs_dim = int(np.prod(model.observation_space.shape))
    act_dim = int(np.prod(model.action_space.shape))
    print(f"loaded {args.model}: obs {obs_dim}, act {act_dim}, "
          f"action_space {model.action_space}, squash_output={model.policy.squash_output}")

    net = DeterministicPolicy(model.policy, model.action_space.low, model.action_space.high).eval()

    # sanity: our forward path must match model.predict(deterministic=True)
    rng = np.random.default_rng(0)
    probe = rng.standard_normal((16, obs_dim)).astype(np.float32)
    with torch.no_grad():
        ours = net(torch.from_numpy(probe)).numpy()
    theirs = np.stack([model.predict(o, deterministic=True)[0] for o in probe])
    d = np.abs(ours - theirs).max()
    print(f"pre-export self-check vs model.predict: max|diff| = {d:.2e}", "OK" if d < 1e-5 else "!! MISMATCH")
    if d >= 1e-5:
        raise SystemExit("forward path does not match SB3 predict -- do not ship this export")

    dummy = torch.zeros(1, obs_dim, dtype=torch.float32)
    torch.onnx.export(
        net, dummy, out,
        input_names=["obs"], output_names=["action"],
        dynamic_axes={"obs": {0: "batch"}, "action": {0: "batch"}},
        opset_version=args.opset,
    )
    try:
        import onnx
        onnx.checker.check_model(onnx.load(out))
        print("onnx.checker: OK")
    except Exception as e:  # noqa: BLE001
        print(f"onnx.checker warning: {e}")
    print(f"wrote {out}  ({os.path.getsize(out)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
