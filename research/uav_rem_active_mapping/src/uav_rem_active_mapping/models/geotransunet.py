from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

def _group_count(channels: int) -> int:
    for groups in (8, 4, 2, 1):
        if channels % groups == 0:
            return groups
    return 1


class ResidualBlock(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        groups = _group_count(channels)
        self.block = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
            nn.GELU(),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, channels),
        )
        self.activation = nn.GELU()

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.activation(inputs + self.block(inputs))


class DownBlock(nn.Module):
    def __init__(self, input_channels: int, output_channels: int) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(input_channels, output_channels, 4, stride=2, padding=1, bias=False),
            nn.GroupNorm(_group_count(output_channels), output_channels),
            nn.GELU(),
            ResidualBlock(output_channels),
        )

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        return self.block(inputs)


class UpBlock(nn.Module):
    def __init__(self, input_channels: int, skip_channels: int, output_channels: int) -> None:
        super().__init__()
        self.up = nn.ConvTranspose2d(input_channels, output_channels, 2, stride=2)
        self.fuse = nn.Sequential(
            nn.Conv2d(output_channels + skip_channels, output_channels, 3, padding=1, bias=False),
            nn.GroupNorm(_group_count(output_channels), output_channels),
            nn.GELU(),
            ResidualBlock(output_channels),
        )

    def forward(self, inputs: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        inputs = self.up(inputs)
        if inputs.shape[-2:] != skip.shape[-2:]:
            inputs = F.interpolate(inputs, size=skip.shape[-2:], mode="bilinear", align_corners=False)
        return self.fuse(torch.cat((inputs, skip), dim=1))


class SamplingPatternEncoder(nn.Module):
    """Encode sparse measurement values and locations before global attention."""

    def __init__(
        self,
        *,
        channels: int,
        attention_heads: int,
        depth: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.input_projection = nn.Linear(2, channels)
        layer = nn.TransformerEncoderLayer(
            d_model=channels,
            nhead=attention_heads,
            dim_feedforward=channels * 2,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer,
            num_layers=depth,
            enable_nested_tensor=False,
        )
        self.output_projection = nn.Linear(channels, channels)
        self.gate = nn.Sequential(nn.Linear(channels * 2, channels), nn.Sigmoid())

    def forward(
        self,
        tokens: torch.Tensor,
        sparse_rss: torch.Tensor,
        observed_mask: torch.Tensor,
        position: torch.Tensor,
        *,
        grid_shape: tuple[int, int],
    ) -> torch.Tensor:
        pooled_mask = F.adaptive_avg_pool2d(observed_mask, grid_shape)
        pooled_sum = F.adaptive_avg_pool2d(sparse_rss, grid_shape)
        pooled_value = pooled_sum / pooled_mask.clamp_min(1e-6)
        descriptor = torch.cat((pooled_value, pooled_mask), dim=1).flatten(2).transpose(1, 2)
        sampling_tokens = self.input_projection(descriptor) + position
        sampling_tokens = self.transformer(sampling_tokens)
        has_observations = (observed_mask.sum(dim=(1, 2, 3), keepdim=True) > 0).to(tokens.dtype)
        sampling_tokens = sampling_tokens * has_observations.view(-1, 1, 1)
        gate = self.gate(torch.cat((tokens, sampling_tokens), dim=-1))
        return tokens + gate * self.output_projection(sampling_tokens)


class GeoTransUNet(nn.Module):
    """Single-height sparse-to-dense REM network with geometry-aware fusion."""

    def __init__(
        self,
        *,
        base_channels: int = 64,
        transformer_depth: int = 6,
        attention_heads: int = 8,
        sampling_depth: int = 2,
        dropout: float = 0.1,
        propagation_refinement: bool = False,
        frequency_height_conditioning: bool = False,
        rss_mean_dbm: float = -70.0,
        rss_std_db: float = 20.0,
        measurement_noise_std_db: float = 0.5,
    ) -> None:
        super().__init__()
        if base_channels % 2:
            raise ValueError("base_channels 必须为偶数")
        if rss_std_db <= 0:
            raise ValueError("rss_std_db必须大于0")
        if measurement_noise_std_db <= 0:
            raise ValueError("measurement_noise_std_db必须大于0")
        self.register_buffer("rss_mean_dbm", torch.tensor(float(rss_mean_dbm), dtype=torch.float32))
        self.register_buffer("rss_std_db", torch.tensor(float(rss_std_db), dtype=torch.float32))
        self.register_buffer(
            "measurement_noise_std_db",
            torch.tensor(float(measurement_noise_std_db), dtype=torch.float32),
        )
        half = base_channels // 2
        self.radio_stem = nn.Sequential(
            nn.Conv2d(3, half, 3, padding=1, bias=False),
            nn.GroupNorm(_group_count(half), half),
            nn.GELU(),
            ResidualBlock(half),
        )
        self.geometry_stem = nn.Sequential(
            nn.Conv2d(5, half, 3, padding=1, bias=False),
            nn.GroupNorm(_group_count(half), half),
            nn.GELU(),
            ResidualBlock(half),
        )
        self.fuse = ResidualBlock(base_channels)
        self.down1 = DownBlock(base_channels, base_channels * 2)
        self.down2 = DownBlock(base_channels * 2, base_channels * 4)
        self.down3 = DownBlock(base_channels * 4, base_channels * 8)
        bottleneck_channels = base_channels * 8
        layer = nn.TransformerEncoderLayer(
            d_model=bottleneck_channels,
            nhead=attention_heads,
            dim_feedforward=bottleneck_channels * 4,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(
            layer,
            num_layers=transformer_depth,
            enable_nested_tensor=False,
        )
        self.position_embedding = nn.Parameter(torch.zeros(1, 16 * 16, bottleneck_channels))
        nn.init.trunc_normal_(self.position_embedding, std=0.02)
        self.sampling_encoder = SamplingPatternEncoder(
            channels=bottleneck_channels,
            attention_heads=attention_heads,
            depth=sampling_depth,
            dropout=dropout,
        )
        self.up2 = UpBlock(bottleneck_channels, base_channels * 4, base_channels * 4)
        self.up1 = UpBlock(base_channels * 4, base_channels * 2, base_channels * 2)
        self.up0 = UpBlock(base_channels * 2, base_channels, base_channels)
        self.mean_head = nn.Conv2d(base_channels, 1, 1)
        self.scale_head = nn.Conv2d(base_channels, 1, 1)
        self.shadow_head = nn.Conv2d(base_channels, 1, 1)
        self.emitter_head = nn.Conv2d(base_channels, 1, 1)
        self.propagation_refinement = bool(propagation_refinement)
        self.frequency_height_conditioning = bool(frequency_height_conditioning)
        if self.frequency_height_conditioning:
            self.condition_encoder = nn.Sequential(
                nn.Linear(2, base_channels * 2),
                nn.GELU(),
                nn.Linear(base_channels * 2, bottleneck_channels * 2),
            )
        if self.propagation_refinement:
            refinement_channels = max(base_channels // 2, 16)
            self.propagation_refiner = nn.Sequential(
                nn.Conv2d(base_channels + 4, refinement_channels, 3, padding=1, bias=False),
                nn.GroupNorm(_group_count(refinement_channels), refinement_channels),
                nn.GELU(),
                nn.Conv2d(refinement_channels, 1, 1),
            )
            nn.init.normal_(self.propagation_refiner[-1].weight, std=1e-3)
            nn.init.zeros_(self.propagation_refiner[-1].bias)

    @staticmethod
    def _condition_vector(value: torch.Tensor | float | None, *, batch: int, default: float, device) -> torch.Tensor:
        if value is None:
            return torch.full((batch,), default, dtype=torch.float32, device=device)
        tensor = torch.as_tensor(value, dtype=torch.float32, device=device)
        if tensor.ndim == 0:
            tensor = tensor.expand(batch)
        return tensor.reshape(batch)

    def forward(
        self,
        features: torch.Tensor,
        *,
        frequency_hz: torch.Tensor | float | None = None,
        height_m: torch.Tensor | float | None = None,
        rss_mean_dbm: torch.Tensor | float | None = None,
        rss_std_db: torch.Tensor | float | None = None,
    ) -> dict[str, torch.Tensor]:
        if features.ndim != 4 or features.shape[1] != 8:
            raise ValueError("GeoTransUNet输入必须为 [B,8,H,W]")
        radio = features[:, (0, 1, 5)]
        geometry = features[:, (2, 3, 4, 6, 7)]
        level0 = self.fuse(torch.cat((self.radio_stem(radio), self.geometry_stem(geometry)), dim=1))
        level1 = self.down1(level0)
        level2 = self.down2(level1)
        level3 = self.down3(level2)
        batch, channels, rows, columns = level3.shape
        if self.frequency_height_conditioning:
            frequency = self._condition_vector(
                frequency_hz,
                batch=batch,
                default=2.4e9,
                device=features.device,
            )
            height = self._condition_vector(height_m, batch=batch, default=13.0, device=features.device)
            condition = torch.stack(((torch.log10(frequency) - 9.0), height / 25.0), dim=-1)
            scale, shift = self.condition_encoder(condition).chunk(2, dim=-1)
            level3 = level3 * (1.0 + 0.1 * torch.tanh(scale[:, :, None, None])) + shift[:, :, None, None]
        tokens = level3.flatten(2).transpose(1, 2)
        position = self.position_embedding
        if position.shape[1] != tokens.shape[1]:
            side = int(position.shape[1] ** 0.5)
            position_map = position.transpose(1, 2).reshape(1, channels, side, side)
            position_map = F.interpolate(position_map, size=(rows, columns), mode="bilinear", align_corners=False)
            position = position_map.flatten(2).transpose(1, 2)
        tokens = tokens + position
        tokens = self.sampling_encoder(
            tokens,
            features[:, 0:1],
            features[:, 1:2],
            position,
            grid_shape=(rows, columns),
        )
        tokens = self.transformer(tokens)
        level3 = tokens.transpose(1, 2).reshape(batch, channels, rows, columns)
        decoded = self.up0(self.up1(self.up2(level3, level2), level1), level0)
        shadow_logits = self.shadow_head(decoded)
        emitter_logits = self.emitter_head(decoded)
        mean_standardized = self.mean_head(decoded)
        if self.propagation_refinement:
            propagation_context = torch.cat((
                decoded,
                torch.sigmoid(emitter_logits),
                torch.sigmoid(shadow_logits),
                features[:, 2:4],
            ), dim=1)
            mean_standardized = mean_standardized + self.propagation_refiner(propagation_context)
        mean_value = self._condition_vector(
            rss_mean_dbm,
            batch=batch,
            default=float(self.rss_mean_dbm),
            device=features.device,
        )[:, None, None, None]
        std_value = self._condition_vector(
            rss_std_db,
            batch=batch,
            default=float(self.rss_std_db),
            device=features.device,
        )[:, None, None, None]
        predicted_mean = mean_value + std_value * mean_standardized
        observed_mask = features[:, 1:2] > 0.5
        observed_dbm = mean_value + std_value * features[:, 0:1]
        mean_dbm = torch.where(observed_mask, observed_dbm, predicted_mean)
        predicted_scale = F.softplus(self.scale_head(decoded)) + 0.25
        scale_db = torch.where(observed_mask, self.measurement_noise_std_db.expand_as(predicted_scale), predicted_scale)
        return {
            "mean_dbm": mean_dbm,
            "scale_db": scale_db,
            "shadow_logits": shadow_logits,
            "emitter_logits": emitter_logits,
            "shadow_probability": torch.sigmoid(shadow_logits),
            "emitter_probability": torch.sigmoid(emitter_logits),
        }
