from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

import torch
from torch import nn
from torch.nn import functional as F


class CandidateAttentionPolicy(nn.Module):
    """CAtNIPP-style candidate policy over a learned REM belief map."""

    def __init__(self, *, belief_channels: int = 8, hidden_channels: int = 128, attention_heads: int = 8, attention_depth: int = 2, dropout: float = 0.1) -> None:
        super().__init__()
        self.map_encoder = nn.Sequential(
            nn.Conv2d(belief_channels, hidden_channels, 5, padding=2, bias=False),
            nn.GroupNorm(8, hidden_channels), nn.GELU(),
            nn.Conv2d(hidden_channels, hidden_channels, 3, padding=1, bias=False),
            nn.GroupNorm(8, hidden_channels), nn.GELU(),
        )
        self.candidate_projection = nn.Linear(hidden_channels + 3, hidden_channels)
        layer = nn.TransformerEncoderLayer(d_model=hidden_channels, nhead=attention_heads, dim_feedforward=hidden_channels * 4, dropout=dropout, activation="gelu", batch_first=True, norm_first=True)
        self.candidate_attention = nn.TransformerEncoder(layer, num_layers=attention_depth, enable_nested_tensor=False)
        self.actor = nn.Linear(hidden_channels, 1)
        self.stop_actor = nn.Sequential(nn.Linear(hidden_channels, hidden_channels), nn.GELU(), nn.Linear(hidden_channels, 1))
        self.critic = nn.Sequential(nn.Linear(hidden_channels, hidden_channels), nn.GELU(), nn.Linear(hidden_channels, 1))

    def forward(self, belief: torch.Tensor, candidate_cells: torch.Tensor, path_cost: torch.Tensor, action_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        if belief.ndim != 4:
            raise ValueError("belief 必须是 [B,C,H,W]")
        if candidate_cells.ndim != 3 or candidate_cells.shape[-1] != 2:
            raise ValueError("candidate_cells 必须是 [B,K,2]")
        batch, _channels, rows, columns = belief.shape
        if candidate_cells.shape[0] != batch or path_cost.shape != candidate_cells.shape[:2]:
            raise ValueError("候选点 batch/K 维度不一致")
        if action_mask.shape != (batch, candidate_cells.shape[1] + 1):
            raise ValueError("action_mask 必须覆盖 K 个候选和 STOP")
        if not action_mask.bool().any(dim=1).all():
            raise ValueError("每个状态至少需要一个可选动作（可为STOP）")
        feature_map = self.map_encoder(belief)
        row = candidate_cells[..., 0].long().clamp(0, rows - 1)
        column = candidate_cells[..., 1].long().clamp(0, columns - 1)
        batch_index = torch.arange(batch, device=belief.device)[:, None]
        local = feature_map.permute(0, 2, 3, 1)[batch_index, row, column]
        coordinates = torch.stack((2.0 * column.to(belief.dtype) / max(columns - 1, 1) - 1.0, 2.0 * row.to(belief.dtype) / max(rows - 1, 1) - 1.0), dim=-1)
        normalized_cost = path_cost.to(belief.dtype) / path_cost.amax(dim=1, keepdim=True).clamp_min(1.0)
        tokens = self.candidate_projection(torch.cat((local, coordinates, normalized_cost[..., None]), dim=-1))
        candidate_valid = action_mask[:, :-1].bool()
        attention_valid = candidate_valid.clone()
        attention_valid[~attention_valid.any(dim=1), 0] = True
        tokens = self.candidate_attention(tokens, src_key_padding_mask=~attention_valid)
        candidate_logits = self.actor(tokens).squeeze(-1)
        global_context = feature_map.mean(dim=(2, 3))
        logits = torch.cat((candidate_logits, self.stop_actor(global_context)), dim=1)
        logits = logits.masked_fill(~action_mask.bool(), torch.finfo(logits.dtype).min)
        return logits, self.critic(global_context).squeeze(-1)


def fixed_probe_reward(previous_mean: torch.Tensor, current_mean: torch.Tensor, target: torch.Tensor, probe_mask: torch.Tensor, *, error_scale_db: float, path_cost_m: torch.Tensor | float = 0.0, distance_scale_m: float = 600.0, distance_weight: float = 0.05) -> torch.Tensor:
    if error_scale_db <= 0 or distance_scale_m <= 0:
        raise ValueError("reward归一化尺度必须为正")
    mask = probe_mask.to(target.dtype)
    dimensions = tuple(range(1, target.ndim))
    denominator = mask.sum(dim=dimensions).clamp_min(1.0)
    previous_rmse = torch.sqrt((((previous_mean - target).square() * mask).sum(dim=dimensions) / denominator).clamp_min(0.0))
    current_rmse = torch.sqrt((((current_mean - target).square() * mask).sum(dim=dimensions) / denominator).clamp_min(0.0))
    distance = torch.as_tensor(path_cost_m, dtype=target.dtype, device=target.device)
    return (previous_rmse - current_rmse) / error_scale_db - distance_weight * distance / distance_scale_m


def generalized_advantage_estimate(rewards: torch.Tensor, values: torch.Tensor, dones: torch.Tensor, *, gamma: float = 1.0, gae_lambda: float = 0.95) -> tuple[torch.Tensor, torch.Tensor]:
    if values.shape[-1] != rewards.shape[-1] + 1:
        raise ValueError("values最后一维必须比rewards多1")
    advantages = torch.zeros_like(rewards)
    running = torch.zeros_like(rewards[..., -1])
    for index in range(rewards.shape[-1] - 1, -1, -1):
        alive = 1.0 - dones[..., index].to(rewards.dtype)
        delta = rewards[..., index] + gamma * values[..., index + 1] * alive - values[..., index]
        running = delta + gamma * gae_lambda * alive * running
        advantages[..., index] = running
    return advantages, advantages + values[..., :-1]


def ppo_loss(logits: torch.Tensor, actions: torch.Tensor, old_log_prob: torch.Tensor, advantages: torch.Tensor, values: torch.Tensor, returns: torch.Tensor, *, clip_ratio: float = 0.2, value_weight: float = 0.5, entropy_weight: float = 0.01) -> dict[str, torch.Tensor]:
    distribution = torch.distributions.Categorical(logits=logits)
    log_prob = distribution.log_prob(actions)
    ratio = torch.exp(log_prob - old_log_prob)
    normalized_advantage = (advantages - advantages.mean()) / advantages.std(unbiased=False).clamp_min(1e-6)
    policy = -torch.minimum(ratio * normalized_advantage, ratio.clamp(1.0 - clip_ratio, 1.0 + clip_ratio) * normalized_advantage).mean()
    value = F.mse_loss(values, returns)
    entropy = distribution.entropy().mean()
    total = policy + value_weight * value - entropy_weight * entropy
    return {"loss": total, "policy_loss": policy.detach(), "value_loss": value.detach(), "entropy": entropy.detach()}


def astar_grid(flyable: Sequence[Sequence[bool]], start: tuple[int, int], goal: tuple[int, int]) -> list[tuple[int, int]]:
    rows, columns = len(flyable), len(flyable[0])
    for point in (start, goal):
        if not (0 <= point[0] < rows and 0 <= point[1] < columns and flyable[point[0]][point[1]]):
            raise ValueError("A*起点和终点必须位于可飞区域")
    frontier: list[tuple[float, float, tuple[int, int]]] = [(0.0, 0.0, start)]
    parent: dict[tuple[int, int], tuple[int, int]] = {}
    cost = {start: 0.0}
    while frontier:
        _priority, current_cost, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while current != start:
                current = parent[current]
                path.append(current)
            return list(reversed(path))
        if current_cost > cost[current]:
            continue
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            neighbour = (current[0] + dr, current[1] + dc)
            if not (0 <= neighbour[0] < rows and 0 <= neighbour[1] < columns and flyable[neighbour[0]][neighbour[1]]):
                continue
            if dr and dc and not (flyable[current[0] + dr][current[1]] and flyable[current[0]][current[1] + dc]):
                continue
            new_cost = current_cost + (math.sqrt(2.0) if dr and dc else 1.0)
            if new_cost < cost.get(neighbour, float("inf")):
                cost[neighbour] = new_cost
                parent[neighbour] = current
                heuristic = math.hypot(goal[0] - neighbour[0], goal[1] - neighbour[1])
                heapq.heappush(frontier, (new_cost + heuristic, new_cost, neighbour))
    raise RuntimeError("A*未找到可飞路径")
