import { useMemo } from "react";

function scanPoints(lidar) {
  if (!lidar?.available || !Array.isArray(lidar.ranges_m)) return [];
  const minimum = Number(lidar.range_min_m) || 0.1;
  const maximum = Math.min(Number(lidar.range_max_m) || 30, 30);
  const firstAngle = Number(lidar.angle_min_rad) || 0;
  const angleStep = Number(lidar.angle_step_rad) || 0;
  return lidar.ranges_m.flatMap((value, index) => {
    const distance = Number(value);
    if (!Number.isFinite(distance) || distance < minimum || distance > maximum) return [];
    const angle = firstAngle + angleStep * index;
    return [[Math.cos(angle) * distance, -Math.sin(angle) * distance]];
  });
}

export default function LidarRadar({ lidar }) {
  const points = useMemo(() => scanPoints(lidar), [lidar]);
  const beams = lidar?.count || lidar?.ranges_m?.length || 0;
  return (
    <section className="uav-lidar-radar" aria-label="Gazebo 二维激光雷达接口">
      <header><span>LiDAR · 2D</span><em>{lidar?.available ? `${beams} beams` : "WAITING"}</em></header>
      <svg viewBox="-32 -32 64 64" role="img" aria-label={lidar?.available ? `LiDAR 已检测到 ${points.length} 个障碍物回波` : "LiDAR 等待扫描数据"}>
        <circle r="30" className="uav-lidar-ring" />
        <circle r="20" className="uav-lidar-ring" />
        <circle r="10" className="uav-lidar-ring" />
        <path d="M-30 0H30M0-30V30" className="uav-lidar-axis" />
        <path d="M0 -2.4 L2.1 2.4 L0 1.2 L-2.1 2.4 Z" className="uav-lidar-vehicle" />
        {points.map(([x, y], index) => <circle key={`${index}-${x}-${y}`} cx={x} cy={y} r="0.62" className="uav-lidar-point" />)}
      </svg>
      <footer><span>{points.length} 回波</span><span>30 m</span></footer>
    </section>
  );
}
