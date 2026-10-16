from __future__ import annotations


def test_candidate_policy_masks_invalid_actions_and_returns_value():
    import torch

    from uav_rem_active_mapping.planning import CandidateAttentionPolicy

    policy = CandidateAttentionPolicy(belief_channels=8, hidden_channels=32, attention_heads=4, attention_depth=1)
    belief = torch.zeros(2, 8, 32, 32)
    candidates = torch.tensor([[[3, 4], [10, 12], [20, 25]], [[2, 2], [8, 9], [15, 16]]])
    path_cost = torch.tensor([[2.0, 8.0, 15.0], [1.0, 5.0, 9.0]])
    mask = torch.tensor([[True, False, True, True], [True, True, False, True]])

    logits, value = policy(belief, candidates, path_cost, mask)

    assert logits.shape == (2, 4)
    assert value.shape == (2,)
    assert logits[0, 1] == torch.finfo(logits.dtype).min
    assert logits[1, 2] == torch.finfo(logits.dtype).min


def test_fixed_probe_reward_is_positive_when_map_improves():
    import torch

    from uav_rem_active_mapping.planning import fixed_probe_reward

    target = torch.zeros(1, 1, 4, 4)
    previous = torch.full_like(target, 10.0)
    current = torch.full_like(target, 4.0)
    probe = torch.ones_like(target)

    reward = fixed_probe_reward(previous, current, target, probe, error_scale_db=20.0)

    assert reward.item() > 0


def test_gae_and_ppo_loss_are_finite():
    import torch

    from uav_rem_active_mapping.planning import generalized_advantage_estimate, ppo_loss

    rewards = torch.tensor([[1.0, 0.5]])
    values = torch.tensor([[0.2, 0.3, 0.0]])
    dones = torch.tensor([[False, True]])
    advantages, returns = generalized_advantage_estimate(rewards, values, dones)
    result = ppo_loss(
        torch.zeros(2, 3),
        torch.tensor([0, 1]),
        torch.full((2,), -1.0986123),
        advantages.flatten(),
        values[:, :-1].flatten(),
        returns.flatten(),
    )

    assert torch.isfinite(result["loss"])


def test_astar_routes_around_building_cells():
    from uav_rem_active_mapping.planning import astar_grid

    flyable = [[True] * 7 for _ in range(7)]
    for row in range(1, 6):
        flyable[row][3] = False

    path = astar_grid(flyable, (3, 1), (3, 5))

    assert path[0] == (3, 1)
    assert path[-1] == (3, 5)
    assert all(flyable[row][column] for row, column in path)
