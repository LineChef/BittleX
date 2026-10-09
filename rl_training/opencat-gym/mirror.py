"""Left/right mirror symmetry for the gait policy (V3 plan, lever R1; docs/rl/v3-retrain-plan.md section 2.5).

The scripted wkF walk is left/right symmetric, so a policy should answer a mirrored situation with the mirrored action. V2.1 doesn't: it holds a
fixed one-sided correction (back-left hip ~60 deg vs back-right ~53) that turned G2 about 140 deg on the real floor. MirrorPPO adds a loss that
pulls the policy toward equivariance, so a one-sided bias can only be corrected through feedback (heading, tilt), which works on any surface.

The mirror is a reflection across the body's x-z plane (y -> -y):
    observation                                       mirrored
    quaternion (x, y, z, w)                           (-x, y, -z, w)     roll and yaw flip, pitch stays
    roll / pitch rate                                 (-r, p)
    projected gravity (gx, gy, gz)                    (gx, -gy, gz)
    gait phase t in [0, 1)                            (t + 0.5) mod 1    wkF mirrored matches itself half a cycle later (to 4.2 deg)
    tilt history (r, p) x 12                          (-r, p)
    roll / pitch angular acceleration                 (-a, b)
    command (fwd, yaw)                                (fwd, -yaw)
    heading input (sin, cos)  [HEADING_OBS only]      (-sin, cos)
    each of the 30 joint-history frames               joints swapped FL<->FR, BR<->BL: [2, 3, 0, 1, 6, 7, 4, 5]
    action (8 joint residuals)                        the same joint swap
No joint sign flips: all eight joints share one sign convention in this URDF (and the half-cycle wkF check above used none).

Layout (opencat_gym_env.SIZE_OBSERVATION): 38 robot-state values [+2 heading input], then 240 joint-history values.
"""
import numpy as np
import torch as th
import torch.nn.functional as F
from gymnasium import spaces
from stable_baselines3 import PPO
from stable_baselines3.common.utils import explained_variance

JOINT_SWAP = np.array([2, 3, 0, 1, 6, 7, 4, 5])
N_FRAMES = 30
PHASE_IDX = 9


import os
# opencat_gym_env.PRIV_DIM: the critic-only values appended last (PRIV_OBS); 24 with G2E_PRIV_YAW (lever heading_blind: + sin / cos of the heading error)
PRIV_YAW = os.environ.get("G2E_PRIV_YAW", "0") not in ("0", "", "false", "False", "no")
PRIV_DIM = 24 if PRIV_YAW else 22
PRIV_NEG = (0, 2, 4, 6, 13) + ((22,) if PRIV_YAW else ())    # roll, roll rate, yaw rate, sideways velocity, ground roll [, sin heading error] flip sign
PRIV_SWAP = {9: 10, 10: 9, 11: 12, 12: 11}      # paw contacts FL<->FR, BR<->BL


def _maps(obs_dim):
    """(perm, sign) so that mirrored = obs[..., perm] * sign, except the phase column, which is shifted separately."""
    priv = obs_dim in (278 + PRIV_DIM, 280 + PRIV_DIM)
    heading = {278: False, 280: True}.get(obs_dim - (PRIV_DIM if priv else 0))
    if heading is None:
        raise ValueError(f"mirror.py supports the 278-value base observation and the 280-value HEADING_OBS one (+{PRIV_DIM} PRIV_OBS), not {obs_dim}")
    perm = list(range(obs_dim))
    sign = np.ones(obs_dim)
    sign[0:4] = [-1, 1, -1, 1]          # quaternion
    sign[4:6] = [-1, 1]                 # rates
    sign[6:9] = [1, -1, 1]              # projected gravity
    for k in range(12):                 # tilt history (roll, pitch) pairs
        sign[10 + 2 * k] = -1
    sign[34] = -1                       # angular acceleration (roll)
    sign[37] = -1                       # commanded yaw
    state = 38
    if heading:
        sign[38] = -1                   # sin of the heading error
        state = 40
    for f in range(N_FRAMES):
        for j in range(8):
            perm[state + 8 * f + j] = state + 8 * f + int(JOINT_SWAP[j])
    if priv:
        base = obs_dim - PRIV_DIM
        for k in PRIV_NEG:
            sign[base + k] = -1
        for a, b in PRIV_SWAP.items():
            perm[base + a] = base + b
    return np.array(perm), sign


def mirror_obs(obs):
    """Mirror a batch of observations (numpy or torch, shape (..., obs_dim))."""
    if isinstance(obs, th.Tensor):
        perm, sign = _maps(obs.shape[-1])
        out = obs[..., th.as_tensor(perm, device=obs.device)] * th.as_tensor(sign, dtype=obs.dtype, device=obs.device)
        out[..., PHASE_IDX] = th.remainder(obs[..., PHASE_IDX] + 0.5, 1.0)
        return out
    obs = np.asarray(obs)
    perm, sign = _maps(obs.shape[-1])
    out = obs[..., perm] * sign
    out[..., PHASE_IDX] = np.mod(obs[..., PHASE_IDX] + 0.5, 1.0)
    return out


def mirror_act(act):
    """Mirror a batch of 8-joint actions (numpy or torch)."""
    return act[..., th.as_tensor(JOINT_SWAP, device=act.device)] if isinstance(act, th.Tensor) else np.asarray(act)[..., JOINT_SWAP]


def mirror_gap(model, obs_batch):
    """How far a policy is from mirror-symmetric on these observations: RMS over the batch of mu(mirror(s)) - mirror(mu(s)), in action units
    (residual / 30 deg). 0 for a perfectly symmetric policy. Reported by the V3 benchmark."""
    obs = th.as_tensor(np.asarray(obs_batch), dtype=th.float32)
    with th.no_grad():
        mu = model.policy.get_distribution(obs).distribution.mean
        mu_m = model.policy.get_distribution(mirror_obs(obs)).distribution.mean
        return float(th.sqrt(F.mse_loss(mu_m, mirror_act(mu))))


class MirrorPPO(PPO):
    """PPO plus  mirror_w * ||mu(M s) - M mu(s)||^2  on the policy mean and  mirror_wv * (V(M s) - V(s))^2 / var(returns)  on the value.

    SB3's PPO.train() body, unchanged except for the two extra terms (marked). Set mirror_w = 0 and it is plain PPO. The attributes are not
    saved in the checkpoint: set them after PPO.load()."""
    mirror_w = 1.0
    mirror_wv = 0.1

    def train(self) -> None:
        self.policy.set_training_mode(True)
        self._update_learning_rate(self.policy.optimizer)
        clip_range = self.clip_range(self._current_progress_remaining)  # type: ignore[operator]
        if self.clip_range_vf is not None:
            clip_range_vf = self.clip_range_vf(self._current_progress_remaining)  # type: ignore[operator]

        entropy_losses, pg_losses, value_losses, clip_fractions, mirror_losses = [], [], [], [], []
        continue_training = True
        ret_var = float(np.var(self.rollout_buffer.returns.flatten())) + 1e-6
        for epoch in range(self.n_epochs):
            approx_kl_divs = []
            for rollout_data in self.rollout_buffer.get(self.batch_size):
                actions = rollout_data.actions
                if isinstance(self.action_space, spaces.Discrete):
                    actions = rollout_data.actions.long().flatten()

                mirror_pair = None
                if self.mirror_w > 0:
                    # one forward pass over [observations, mirrored observations] gives SB3's evaluate_actions() outputs for the real half
                    # and the mirrored policy mean / value for the other half (about 2x the batch, not 3 passes)
                    obs = rollout_data.observations
                    n = obs.shape[0]
                    feats = self.policy.extract_features(th.cat([obs, mirror_obs(obs)], dim=0))
                    if self.policy.share_features_extractor:
                        latent_pi, latent_vf = self.policy.mlp_extractor(feats)
                    else:                       # separate actor / critic extractors (priv_policy.PrivCriticPolicy: the actor's masks the privileged values)
                        latent_pi = self.policy.mlp_extractor.forward_actor(feats[0])
                        latent_vf = self.policy.mlp_extractor.forward_critic(feats[1])
                    mean_all = self.policy.action_net(latent_pi)
                    dist = self.policy.action_dist.proba_distribution(mean_all[:n], self.policy.log_std)
                    log_prob, entropy = dist.log_prob(actions), dist.entropy()
                    values_all = self.policy.value_net(latent_vf).flatten()
                    values = values_all[:n]
                    mirror_pair = (mean_all[:n], mean_all[n:], values_all[n:])
                else:
                    values, log_prob, entropy = self.policy.evaluate_actions(rollout_data.observations, actions)
                    values = values.flatten()
                advantages = rollout_data.advantages
                if self.normalize_advantage and len(advantages) > 1:
                    advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

                ratio = th.exp(log_prob - rollout_data.old_log_prob)
                policy_loss_1 = advantages * ratio
                policy_loss_2 = advantages * th.clamp(ratio, 1 - clip_range, 1 + clip_range)
                policy_loss = -th.min(policy_loss_1, policy_loss_2).mean()

                pg_losses.append(policy_loss.item())
                clip_fraction = th.mean((th.abs(ratio - 1) > clip_range).float()).item()
                clip_fractions.append(clip_fraction)

                if self.clip_range_vf is None:
                    values_pred = values
                else:
                    values_pred = rollout_data.old_values + th.clamp(
                        values - rollout_data.old_values, -clip_range_vf, clip_range_vf
                    )
                value_loss = F.mse_loss(rollout_data.returns, values_pred)
                value_losses.append(value_loss.item())

                if entropy is None:
                    entropy_loss = -th.mean(-log_prob)
                else:
                    entropy_loss = -th.mean(entropy)
                entropy_losses.append(entropy_loss.item())

                loss = policy_loss + self.ent_coef * entropy_loss + self.vf_coef * value_loss

                # --- mirror symmetry (the only change from SB3's PPO.train) ---
                if mirror_pair is not None:
                    mu, mu_m, v_m = mirror_pair
                    mirror_loss = F.mse_loss(mu_m, mirror_act(mu))
                    loss = loss + self.mirror_w * mirror_loss
                    if self.mirror_wv > 0:
                        loss = loss + self.mirror_wv * F.mse_loss(v_m, values) / ret_var
                    mirror_losses.append(mirror_loss.item())
                # --- end ---

                with th.no_grad():
                    log_ratio = log_prob - rollout_data.old_log_prob
                    approx_kl_div = th.mean((th.exp(log_ratio) - 1) - log_ratio).cpu().numpy()
                    approx_kl_divs.append(approx_kl_div)

                if self.target_kl is not None and approx_kl_div > 1.5 * self.target_kl:
                    continue_training = False
                    if self.verbose >= 1:
                        print(f"Early stopping at step {epoch} due to reaching max kl: {approx_kl_div:.2f}")
                    break

                self.policy.optimizer.zero_grad()
                loss.backward()
                th.nn.utils.clip_grad_norm_(self.policy.parameters(), self.max_grad_norm)
                self.policy.optimizer.step()

            self._n_updates += 1
            if not continue_training:
                break

        explained_var = explained_variance(self.rollout_buffer.values.flatten(), self.rollout_buffer.returns.flatten())
        self.logger.record("train/entropy_loss", np.mean(entropy_losses))
        self.logger.record("train/policy_gradient_loss", np.mean(pg_losses))
        self.logger.record("train/value_loss", np.mean(value_losses))
        self.logger.record("train/approx_kl", np.mean(approx_kl_divs))
        self.logger.record("train/clip_fraction", np.mean(clip_fractions))
        self.logger.record("train/loss", loss.item())
        self.logger.record("train/explained_variance", explained_var)
        if mirror_losses:
            self.logger.record("train/mirror_loss", np.mean(mirror_losses))
        if hasattr(self.policy, "log_std"):
            self.logger.record("train/std", th.exp(self.policy.log_std).mean().item())
        self.logger.record("train/n_updates", self._n_updates, exclude="tensorboard")
        self.logger.record("train/clip_range", clip_range)
        if self.clip_range_vf is not None:
            self.logger.record("train/clip_range_vf", clip_range_vf)
