"""Privileged critic (2026-10-08 training upgrade, lever `privileged_critic`; docs/plan-detail/handoff-2026-10-08.md section 12).

With G2E_PRIV_OBS the env appends opencat_gym_env.PRIV_DIM values to the observation: the true orientation, rates, body velocity and height, the foot contacts and
the episode's hazards. Only the CRITIC may use them. PrivCriticPolicy gives the actor its own feature extractor that zeroes those values, so the actor's weights on
them get no gradient and its output never depends on them: on G2 (and in the ONNX export) the same actor runs on the plain observation with zeros in their place.
"""
import torch as th
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.torch_layers import FlattenExtractor


class MaskTail(FlattenExtractor):
    """Flatten, then zero the last `n` features (the privileged values)."""
    def __init__(self, observation_space, n: int):
        super().__init__(observation_space)
        self.n = int(n)

    def forward(self, observations: th.Tensor) -> th.Tensor:
        x = super().forward(observations)
        if self.n <= 0:
            return x
        return th.cat([x[..., :-self.n], th.zeros_like(x[..., -self.n:])], dim=-1)


class PrivCriticPolicy(ActorCriticPolicy):
    """ActorCriticPolicy whose actor never sees the last `priv_dim` observation values (the critic sees everything)."""
    def __init__(self, *args, priv_dim: int = 0, **kwargs):
        kwargs["share_features_extractor"] = False
        super().__init__(*args, **kwargs)
        self.priv_dim = int(priv_dim)
        self.pi_features_extractor = MaskTail(self.observation_space, self.priv_dim)
        self.features_extractor = self.pi_features_extractor

    def _get_constructor_parameters(self):
        data = super()._get_constructor_parameters()
        data["priv_dim"] = self.priv_dim
        return data
