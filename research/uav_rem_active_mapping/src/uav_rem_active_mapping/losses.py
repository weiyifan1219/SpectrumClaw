from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (values * mask).sum() / mask.sum().clamp_min(1.0)


def _gradient_loss(prediction: torch.Tensor, target: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    horizontal_mask = mask[..., :, 1:] * mask[..., :, :-1]
    vertical_mask = mask[..., 1:, :] * mask[..., :-1, :]
    horizontal = torch.abs(
        (prediction[..., :, 1:] - prediction[..., :, :-1])
        - (target[..., :, 1:] - target[..., :, :-1])
    )
    vertical = torch.abs(
        (prediction[..., 1:, :] - prediction[..., :-1, :])
        - (target[..., 1:, :] - target[..., :-1, :])
    )
    return _masked_mean(horizontal, horizontal_mask) + _masked_mean(vertical, vertical_mask)


def _masked_pool(values: torch.Tensor, mask: torch.Tensor, factor: int) -> tuple[torch.Tensor, torch.Tensor]:
    pooled_mask = F.avg_pool2d(mask, factor, factor)
    pooled_values = F.avg_pool2d(values * mask, factor, factor) / pooled_mask.clamp_min(1e-6)
    return pooled_values, (pooled_mask > 0).to(values.dtype)


class ShadowAwareLoss(nn.Module):
    def __init__(
        self,
        *,
        rss_std_db: float = 1.0,
        shadow_weight: float = 2.0,
        boundary_weight: float = 0.0,
        mse_weight: float = 0.0,
        uncertainty_weight: float = 0.1,
        gradient_weight: float = 0.2,
        multiscale_weight: float = 0.1,
        emitter_weight: float = 0.05,
        shadow_aux_weight: float = 0.05,
        smooth_l1_beta: float = 0.1,
    ) -> None:
        super().__init__()
        if rss_std_db <= 0:
            raise ValueError("rss_std_db必须大于0")
        self.rss_std_db = float(rss_std_db)
        self.shadow_weight = float(shadow_weight)
        self.boundary_weight = float(boundary_weight)
        self.mse_weight = float(mse_weight)
        self.uncertainty_weight = float(uncertainty_weight)
        self.gradient_weight = float(gradient_weight)
        self.multiscale_weight = float(multiscale_weight)
        self.emitter_weight = float(emitter_weight)
        self.shadow_aux_weight = float(shadow_aux_weight)
        self.smooth_l1_beta = float(smooth_l1_beta)

    def forward(self, outputs: dict[str, torch.Tensor], batch: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
        target = batch["target_dbm"]
        valid = batch["valid_mask"].to(target.dtype)
        blind = valid * (1.0 - batch["observed_mask"].to(target.dtype))
        shadow_target = batch["shadow_target"].to(target.dtype)
        emitter_target = batch["emitter_target"].to(target.dtype)
        mean = outputs["mean_dbm"]
        scale = outputs["scale_db"].clamp(0.25, 30.0)
        boundary = torch.zeros_like(shadow_target)
        boundary[..., :, 1:] = torch.maximum(
            boundary[..., :, 1:],
            torch.abs(shadow_target[..., :, 1:] - shadow_target[..., :, :-1]),
        )
        boundary[..., 1:, :] = torch.maximum(
            boundary[..., 1:, :],
            torch.abs(shadow_target[..., 1:, :] - shadow_target[..., :-1, :]),
        )
        boundary = F.max_pool2d(boundary, kernel_size=3, stride=1, padding=1)
        spatial_weight = 1.0 + self.shadow_weight * shadow_target + self.boundary_weight * boundary
        weighted_blind = blind * spatial_weight
        if "rss_std_db" in batch:
            rss_std = batch["rss_std_db"].to(target.dtype).reshape(-1, 1, 1, 1)
        else:
            rss_std = target.new_full((target.shape[0], 1, 1, 1), self.rss_std_db)
        normalized_mean = mean / rss_std
        normalized_target = target / rss_std
        normalized_scale = scale / rss_std
        reconstruction = _masked_mean(
            F.smooth_l1_loss(
                normalized_mean,
                normalized_target,
                reduction="none",
                beta=self.smooth_l1_beta,
            ),
            weighted_blind,
        )
        mse = _masked_mean((normalized_mean - normalized_target).square(), weighted_blind)
        uncertainty_nll = _masked_mean(
            torch.abs(normalized_target - normalized_mean) / normalized_scale
            + torch.log(normalized_scale),
            weighted_blind,
        )
        gradient = _gradient_loss(normalized_mean, normalized_target, blind)
        multiscale = target.new_zeros(())
        for factor in (2, 4):
            pooled_mean, pooled_mask = _masked_pool(normalized_mean, blind, factor)
            pooled_target, _ = _masked_pool(normalized_target, blind, factor)
            multiscale = multiscale + _masked_mean(torch.abs(pooled_mean - pooled_target), pooled_mask)
        shadow_aux = _masked_mean(
            F.binary_cross_entropy_with_logits(outputs["shadow_logits"], shadow_target, reduction="none"),
            valid,
        )
        emitter_aux = _masked_mean(
            F.binary_cross_entropy_with_logits(outputs["emitter_logits"], emitter_target, reduction="none"),
            valid,
        )
        total = (
            reconstruction
            + self.mse_weight * mse
            + self.uncertainty_weight * uncertainty_nll
            + self.gradient_weight * gradient
            + self.multiscale_weight * multiscale
            + self.emitter_weight * emitter_aux
            + self.shadow_aux_weight * shadow_aux
        )
        return {
            "loss": total,
            "reconstruction_loss": reconstruction.detach(),
            "mse_loss": mse.detach(),
            "uncertainty_nll": uncertainty_nll.detach(),
            "gradient_loss": gradient.detach(),
            "multiscale_loss": multiscale.detach(),
            "emitter_loss": emitter_aux.detach(),
            "shadow_loss": shadow_aux.detach(),
            "boundary_fraction": _masked_mean(boundary, valid).detach(),
        }
