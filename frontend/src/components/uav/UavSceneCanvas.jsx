import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import LidarRadar from "./LidarRadar.jsx";

// Coordinates are Gazebo ENU.  Keep this layout in lockstep with
// simulation/worlds/urban_block.sdf so browser rendering, camera images and
// LiDAR returns all describe the same obstacle field.
const URBAN_BUILDINGS = [
  { position: [13, 12, 9], size: [10, 10, 18], color: 0x5c788f },
  { position: [-13, 14, 11], size: [9, 8, 22], color: 0x9b686b },
  { position: [-16, -11, 7.5], size: [12, 10, 15], color: 0xa97e4e },
  { position: [14, -14, 5], size: [16, 8, 10], color: 0x4e887a },
  { position: [0, 25, 5.5], size: [18, 7, 11], color: 0x6268a0 },
  { position: [-27, 7, 6], size: [10, 10, 12], color: 0x689786 },
];
const URBAN_TREES = [[8, 9], [-8, 10], [-9, -8], [9, -8]];

function makeDrone() {
  const group = new THREE.Group();
  const bodyMaterial = new THREE.MeshStandardMaterial({ color: 0x0b1520, metalness: 0.45, roughness: 0.38 });
  const accentMaterial = new THREE.MeshStandardMaterial({ color: 0x1bb9d8, emissive: 0x07576b, emissiveIntensity: 0.85, metalness: 0.5, roughness: 0.28 });
  const rotorMaterial = new THREE.MeshStandardMaterial({ color: 0x2c4658, metalness: 0.4, roughness: 0.6 });
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.16, 0.38), bodyMaterial);
  body.position.y = 0.06;
  group.add(body);
  const core = new THREE.Mesh(new THREE.CylinderGeometry(0.19, 0.19, 0.18, 16), accentMaterial);
  core.rotation.x = Math.PI / 2;
  core.position.y = 0.06;
  group.add(core);
  const armGeometry = new THREE.BoxGeometry(1.12, 0.06, 0.055);
  for (const yaw of [Math.PI / 4, -Math.PI / 4]) {
    const arm = new THREE.Mesh(armGeometry, bodyMaterial);
    arm.rotation.y = yaw;
    arm.position.y = 0.1;
    group.add(arm);
  }
  for (const [x, z] of [[0.39, 0.39], [0.39, -0.39], [-0.39, 0.39], [-0.39, -0.39]]) {
    const motor = new THREE.Mesh(new THREE.CylinderGeometry(0.065, 0.065, 0.11, 12), rotorMaterial);
    motor.position.set(x, 0.14, z);
    group.add(motor);
    const rotor = new THREE.Mesh(new THREE.CylinderGeometry(0.26, 0.26, 0.012, 20), accentMaterial);
    rotor.scale.z = 0.13;
    rotor.position.set(x, 0.205, z);
    group.add(rotor);
  }
  const heading = new THREE.Mesh(new THREE.ConeGeometry(0.09, 0.26, 10), accentMaterial);
  heading.rotation.x = Math.PI / 2;
  heading.position.set(0.37, 0.06, 0);
  group.add(heading);
  return group;
}

function toThreePosition(position) {
  if (!Array.isArray(position) || position.length !== 3) return [0, 0.16, 0];
  // Gazebo uses ENU; Three's up-axis is Y.
  return [Number(position[0]) || 0, Math.max(0.16, Number(position[2]) || 0), -(Number(position[1]) || 0)];
}

function yawFromQuaternion(quaternion) {
  if (!Array.isArray(quaternion) || quaternion.length !== 4) return 0;
  const [x, y, z, w] = quaternion.map(Number);
  return Math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z));
}

function addUrbanBlock(scene) {
  const roadMaterial = new THREE.MeshStandardMaterial({ color: 0x16212a, roughness: 0.94, metalness: 0.05 });
  const roadX = new THREE.Mesh(new THREE.BoxGeometry(100, 0.05, 7), roadMaterial);
  roadX.position.y = 0.025;
  roadX.receiveShadow = true;
  scene.add(roadX);
  const roadY = new THREE.Mesh(new THREE.BoxGeometry(7, 0.06, 100), roadMaterial);
  roadY.position.y = 0.03;
  roadY.receiveShadow = true;
  scene.add(roadY);

  for (const { position: [x, y, z], size: [width, depth, height], color } of URBAN_BUILDINGS) {
    const building = new THREE.Group();
    building.position.set(x, z, -y);
    const facade = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      new THREE.MeshStandardMaterial({ color, roughness: 0.68, metalness: 0.15 }),
    );
    facade.castShadow = true;
    facade.receiveShadow = true;
    building.add(facade);
    const roof = new THREE.Mesh(
      new THREE.BoxGeometry(width * 0.72, 0.5, depth * 0.72),
      new THREE.MeshStandardMaterial({ color: 0x18232c, roughness: 0.82, metalness: 0.18 }),
    );
    roof.position.y = height / 2 + 0.25;
    roof.castShadow = true;
    building.add(roof);
    scene.add(building);
  }

  const trunkMaterial = new THREE.MeshStandardMaterial({ color: 0x5a3517, roughness: 0.98 });
  const foliageMaterial = new THREE.MeshStandardMaterial({ color: 0x237b43, roughness: 0.95 });
  for (const [x, y] of URBAN_TREES) {
    const tree = new THREE.Group();
    tree.position.set(x, 0, -y);
    const trunk = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.34, 4, 10), trunkMaterial);
    trunk.position.y = 2;
    trunk.castShadow = true;
    tree.add(trunk);
    const foliage = new THREE.Mesh(new THREE.SphereGeometry(2.1, 14, 10), foliageMaterial);
    foliage.position.y = 5;
    foliage.castShadow = true;
    tree.add(foliage);
    scene.add(tree);
  }
}

export default function UavSceneCanvas({ vehicle, lidar, connection, controlOverlay }) {
  const mountRef = useRef(null);
  const vehicleRef = useRef(vehicle);
  const lidarRef = useRef(lidar);
  const [error, setError] = useState("");
  vehicleRef.current = vehicle;
  lidarRef.current = lidar;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: "high-performance" });
    } catch {
      setError("当前浏览器无法启用 WebGL；可切换到五路相机视图继续调试。");
      return undefined;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x07131d);
    scene.fog = new THREE.FogExp2(0x07131d, 0.026);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500);
    camera.position.set(9, 6.6, 9);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.8, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.minDistance = 2.8;
    controls.maxDistance = 38;
    // This is a follow camera, not a free editor camera: users can orbit and
    // zoom, but cannot pan the aircraft away from the centre of the viewport.
    controls.enablePan = false;

    scene.add(new THREE.HemisphereLight(0x9edfff, 0x07131d, 1.6));
    const sun = new THREE.DirectionalLight(0x86d4ff, 2.1);
    sun.position.set(8, 14, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    scene.add(sun);
    const ground = new THREE.Mesh(
      new THREE.PlaneGeometry(120, 120),
      new THREE.MeshStandardMaterial({ color: 0x274533, roughness: 0.93, metalness: 0.04 }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    scene.add(ground);
    const grid = new THREE.GridHelper(120, 120, 0x326050, 0x254a3e);
    grid.position.y = 0.012;
    scene.add(grid);
    addUrbanBlock(scene);
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(1.6, 1.6, 0.04, 48),
      new THREE.MeshStandardMaterial({ color: 0x123f4d, emissive: 0x073e4a, emissiveIntensity: 0.75, roughness: 0.55 }),
    );
    pad.position.y = 0.025;
    pad.receiveShadow = true;
    scene.add(pad);
    const drone = makeDrone();
    drone.castShadow = true;
    scene.add(drone);
    const beacon = new THREE.PointLight(0x33d9ff, 2, 8, 2);
    beacon.position.set(0, 0.5, 0);
    scene.add(beacon);

    // The server forwards a bounded, down-sampled copy of the real Gazebo
    // LaserScan.  Keep the buffer local so rendering is browser-GPU work.
    const lidarGeometry = new THREE.BufferGeometry();
    const lidarPositions = new Float32Array(180 * 3);
    lidarGeometry.setAttribute("position", new THREE.BufferAttribute(lidarPositions, 3));
    lidarGeometry.setDrawRange(0, 0);
    const lidarPoints = new THREE.Points(
      lidarGeometry,
      new THREE.PointsMaterial({ color: 0x65f5ce, size: 0.12, sizeAttenuation: true, transparent: true, opacity: 0.88 }),
    );
    lidarPoints.position.y = 0.22;
    drone.add(lidarPoints);
    const lidarRing = new THREE.LineLoop(
      new THREE.BufferGeometry().setFromPoints(
        Array.from({ length: 64 }, (_, index) => {
          const angle = (index / 64) * Math.PI * 2;
          return new THREE.Vector3(Math.cos(angle) * 6, 0.21, Math.sin(angle) * 6);
        }),
      ),
      new THREE.LineBasicMaterial({ color: 0x217664, transparent: true, opacity: 0.35 }),
    );
    drone.add(lidarRing);
    let lidarTimestamp = 0;

    const updateLidar = (scan) => {
      if (!scan?.available || !Array.isArray(scan.ranges_m) || scan.updated_at === lidarTimestamp) return;
      lidarTimestamp = scan.updated_at;
      const minRange = Number(scan.range_min_m) || 0.1;
      const maxRange = Math.min(Number(scan.range_max_m) || 30, 30);
      const angleMin = Number(scan.angle_min_rad) || 0;
      const angleStep = Number(scan.angle_step_rad) || 0;
      const sourceCount = scan.ranges_m.length;
      const count = Math.min(sourceCount, 180);
      for (let index = 0; index < count; index += 1) {
        const sourceIndex = Math.min(sourceCount - 1, Math.floor((index * sourceCount) / count));
        const value = Number(scan.ranges_m[sourceIndex]);
        // No obstacle return is rendered at the sensor's maximum range, so an
        // empty world still visibly confirms the live LiDAR sweep.
        const range = Number.isFinite(value) && value >= minRange ? Math.min(value, maxRange) : maxRange;
        const angle = angleMin + angleStep * sourceIndex;
        lidarPositions[index * 3] = Math.cos(angle) * range;
        lidarPositions[index * 3 + 1] = 0;
        lidarPositions[index * 3 + 2] = Math.sin(angle) * range;
      }
      lidarGeometry.setDrawRange(0, count);
      lidarGeometry.attributes.position.needsUpdate = true;
      lidarRing.scale.setScalar(Math.max(0.03, maxRange / 6));
    };

    const resize = () => {
      const { width, height } = mount.getBoundingClientRect();
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(mount);
    resize();
    let raf = 0;
    const target = new THREE.Vector3();
    const followTarget = new THREE.Vector3();
    const cameraDelta = new THREE.Vector3();
    const animate = () => {
      const live = vehicleRef.current;
      if (live?.available) {
        target.set(...toThreePosition(live.position_m));
        drone.position.lerp(target, 0.2);
        drone.rotation.y = -yawFromQuaternion(live.quaternion_xyzw);
        beacon.position.copy(drone.position).add(new THREE.Vector3(0, 0.5, 0));
      }
      // Translate camera and orbit target by the same amount. This preserves
      // the user's chosen angle and zoom while keeping the real drone centred.
      followTarget.copy(drone.position).add(new THREE.Vector3(0, 0.2, 0));
      cameraDelta.subVectors(followTarget, controls.target);
      camera.position.add(cameraDelta);
      controls.target.copy(followTarget);
      updateLidar(lidarRef.current);
      controls.update();
      renderer.render(scene, camera);
      raf = window.requestAnimationFrame(animate);
    };
    animate();
    return () => {
      window.cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      lidarGeometry.dispose();
      lidarPoints.material.dispose();
      lidarRing.geometry.dispose();
      lidarRing.material.dispose();
      renderer.dispose();
      mount.replaceChildren();
    };
  }, []);

  if (error) return <div className="uav-viewer-pending" role="alert"><strong>本地三维渲染不可用</strong><span>{error}</span></div>;
  const position = vehicle?.position_m?.map((v) => Number(v).toFixed(2)).join(" · ") || "等待 Gazebo 位姿";
  const lidarLabel = lidar?.available ? `LiDAR · ${lidar.count || lidar.ranges_m?.length || 0} beams` : "LiDAR · 等待扫描";
  return (
    <div className="uav-local-scene" aria-label="本地 WebGL 无人机三维视图">
      <div ref={mountRef} className="uav-local-scene-canvas" />
      <div className="uav-scene-hud top-left">LOCAL WEBGL · 城市街区 · {connection === "online" ? "LIVE" : connection === "connecting" ? "CONNECTING" : "RECONNECTING"}</div>
      <div className="uav-scene-hud top-right">{lidarLabel}</div>
      <LidarRadar lidar={lidar} />
      {controlOverlay}
      <div className="uav-scene-hud bottom-left">ENU x/y/z · {position}</div>
      <div className="uav-scene-hud bottom-right">跟随锁定 · 拖拽旋转 · 滚轮缩放</div>
    </div>
  );
}
