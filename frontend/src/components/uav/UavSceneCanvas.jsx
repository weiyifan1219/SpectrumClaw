import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const RAY_COLORS = ["#f7c948", "#48d8ff", "#b787ff", "#ff7a9f", "#64e7a3", "#ff9f43", "#83a7ff"];

function pathColor(path, anchorId) {
  const key = `${anchorId || ""}:${path.id || ""}`;
  const index = [...key].reduce((total, character) => total + character.charCodeAt(0), 0) % RAY_COLORS.length;
  return RAY_COLORS[index];
}

// Coordinates are Gazebo ENU.  Keep this layout in lockstep with
// simulation/worlds/urban_block.sdf so browser rendering, camera images and
// LiDAR returns all describe the same obstacle field.
const URBAN_BUILDINGS = [
  { position: [13, 12, 9], size: [10, 10, 18] },
  { position: [-13, 14, 11], size: [9, 8, 22] },
  { position: [-16, -11, 7.5], size: [12, 10, 15] },
  { position: [14, -14, 5], size: [16, 8, 10] },
  { position: [0, 25, 5.5], size: [18, 7, 11] },
  { position: [-27, 7, 6], size: [10, 10, 12] },
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

  for (const { position: [x, y, z], size: [width, depth, height] } of URBAN_BUILDINGS) {
    const building = new THREE.Group();
    building.position.set(x, z, -y);
    const facade = new THREE.Mesh(
      new THREE.BoxGeometry(width, height, depth),
      new THREE.MeshStandardMaterial({ color: 0x38566a, roughness: 0.74, metalness: 0.12 }),
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

function combinedPowerDbm(anchors) {
  const totalMw = anchors.reduce((total, anchor) => {
    const powerDbm = Number(anchor?.received_power_dbm);
    return Number.isFinite(powerDbm) ? total + (10 ** (powerDbm / 10)) : total;
  }, 0);
  return totalMw > 0 ? 10 * Math.log10(totalMw) : null;
}

export default function UavSceneCanvas({ vehicle, connection, controlOverlay, spectrumSituation, transmitters = [], selectedTransmitter = "all", onSelectTransmitter }) {
  const mountRef = useRef(null);
  const vehicleRef = useRef(vehicle);
  const spectrumRef = useRef(spectrumSituation);
  const transmittersRef = useRef(transmitters);
  const selectedTransmitterRef = useRef(selectedTransmitter);
  const [error, setError] = useState("");
  vehicleRef.current = vehicle;
  spectrumRef.current = spectrumSituation;
  transmittersRef.current = transmitters;
  selectedTransmitterRef.current = selectedTransmitter;

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
    const spectrumMode = Boolean(spectrumRef.current);
    scene.fog = new THREE.FogExp2(0x07131d, spectrumMode ? 0.016 : 0.026);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 500);
    camera.position.set(...(spectrumMode ? [26, 20, 26] : [9, 6.6, 9]));
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 0.8, 0);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.maxPolarAngle = Math.PI * 0.47;
    controls.minDistance = 2.8;
    controls.maxDistance = spectrumMode ? 82 : 38;
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

    // RF objects deliberately live in the same ENU-to-Three conversion as
    // the aircraft and city.  Every line below is an actual Sionna path
    // returned by the measurement API; no visual interpolation or heat-map
    // is manufactured in the browser.
    const radioOverlay = new THREE.Group();
    scene.add(radioOverlay);
    let radioSignature = "";
    const disposeGroup = (group) => {
      group.traverse((node) => {
        node.geometry?.dispose?.();
        if (Array.isArray(node.material)) node.material.forEach((material) => material.dispose?.());
        else node.material?.dispose?.();
      });
    };
    const addRadioSource = (id, position, active) => {
      const source = new THREE.Group();
      const [x, y, z] = toThreePosition(position);
      source.position.set(x, y, z);
      const glow = new THREE.PointLight(active ? 0x63ebbb : 0x38bfe8, active ? 4.6 : 1.85, 34, 2);
      source.add(glow);
      const towerMaterial = new THREE.MeshStandardMaterial({ color: active ? 0x75e9bd : 0x3d97b6, emissive: active ? 0x0b5a42 : 0x07394b, emissiveIntensity: 1.25, metalness: 0.48, roughness: 0.3 });
      const mast = new THREE.Mesh(
        new THREE.CylinderGeometry(0.075, 0.12, Math.max(2.1, y), 10), towerMaterial,
      );
      mast.position.y = -Math.max(2.1, y) / 2;
      source.add(mast);
      const groundRing = new THREE.Mesh(
        new THREE.TorusGeometry(0.78, 0.035, 8, 32),
        new THREE.MeshBasicMaterial({ color: active ? 0x7cebc2 : 0x45b9db, transparent: true, opacity: 0.72 }),
      );
      groundRing.rotation.x = Math.PI / 2;
      groundRing.position.y = -y + 0.05;
      source.add(groundRing);
      const cap = new THREE.Mesh(
        new THREE.SphereGeometry(0.27, 14, 10),
        new THREE.MeshStandardMaterial({ color: 0xc9fff0, emissive: active ? 0x4ce5ad : 0x20738e, emissiveIntensity: 1.6, roughness: 0.3 }),
      );
      source.add(cap);
      source.userData.id = id;
      radioOverlay.add(source);
    };
    const updateSpectrumOverlay = () => {
      const observation = spectrumRef.current?.observation;
      const allAnchors = Array.isArray(observation?.anchors) ? observation.anchors : [];
      const selected = selectedTransmitterRef.current;
      const anchors = selected === "all" ? allAnchors : allAnchors.filter((anchor) => anchor.id === selected);
      const sources = Array.isArray(transmittersRef.current) ? transmittersRef.current : [];
      const signature = JSON.stringify({
        sources: sources.map((source) => [source.id, source.position_m]),
        selected,
        paths: anchors.map((anchor) => [anchor.id, anchor.ray_paths]),
      });
      if (signature === radioSignature) return;
      radioSignature = signature;
      disposeGroup(radioOverlay);
      radioOverlay.clear();
      const sourceIdsWithPaths = new Set(anchors.filter((anchor) => Array.isArray(anchor.ray_paths) && anchor.ray_paths.length).map((anchor) => anchor.id));
      sources.forEach((source) => {
        const position = Array.isArray(source.position_m) ? source.position_m : [0, 0];
        const sourcePosition = position.length >= 3 ? position.slice(0, 3) : [position[0] || 0, position[1] || 0, Number(source.altitude_m) || 12];
        addRadioSource(source.id, sourcePosition, sourceIdsWithPaths.has(source.id));
      });
      anchors.forEach((anchor) => {
        (Array.isArray(anchor.ray_paths) ? anchor.ray_paths : []).forEach((path) => {
          const points = Array.isArray(path.points_m) ? path.points_m : [];
          if (points.length < 2) return;
          const vertices = points.map((point) => new THREE.Vector3(...toThreePosition(point)));
          const color = new THREE.Color(pathColor(path, anchor.id));
          const glowGeometry = new THREE.BufferGeometry().setFromPoints(vertices);
          const glowLine = new THREE.Line(glowGeometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.24 }));
          radioOverlay.add(glowLine);
          const geometry = new THREE.BufferGeometry().setFromPoints(vertices);
          const line = new THREE.Line(geometry, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.94 }));
          radioOverlay.add(line);
          points.slice(1, -1).forEach((point) => {
            const marker = new THREE.Mesh(
              new THREE.SphereGeometry(0.16, 10, 8),
              new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 1.1, roughness: 0.38 }),
            );
            marker.position.set(...toThreePosition(point));
            radioOverlay.add(marker);
            const ring = new THREE.Mesh(
              new THREE.TorusGeometry(0.29, 0.028, 8, 18),
              new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.8 }),
            );
            ring.rotation.x = Math.PI / 2;
            ring.position.copy(marker.position);
            radioOverlay.add(ring);
          });
        });
      });
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
      updateSpectrumOverlay();
      controls.update();
      renderer.render(scene, camera);
      raf = window.requestAnimationFrame(animate);
    };
    animate();
    return () => {
      window.cancelAnimationFrame(raf);
      observer.disconnect();
      controls.dispose();
      disposeGroup(radioOverlay);
      renderer.dispose();
      mount.replaceChildren();
    };
  }, []);

  if (error) return <div className="uav-viewer-pending" role="alert"><strong>本地三维渲染不可用</strong><span>{error}</span></div>;
  const position = vehicle?.position_m?.map((v) => Number(v).toFixed(2)).join(" · ") || "等待 Gazebo 位姿";
  const anchors = spectrumSituation?.observation?.anchors || [];
  const pathCount = anchors
    .filter((anchor) => selectedTransmitter === "all" || anchor.id === selectedTransmitter)
    .reduce((total, anchor) => total + (Array.isArray(anchor.ray_paths) ? anchor.ray_paths.length : 0), 0);
  const transmitterIds = [...new Set([
    ...transmitters.map((transmitter) => transmitter.id),
    ...anchors.map((anchor) => anchor.id),
  ].filter(Boolean))];
  const linkCards = [
    { id: "all", label: "全局态势", powerDbm: combinedPowerDbm(anchors), paths: anchors.reduce((total, anchor) => total + (anchor.ray_paths?.length || 0), 0) },
    ...transmitterIds.map((id) => {
      const anchor = anchors.find((item) => item.id === id);
      return { id, label: `${id} 链路`, powerDbm: Number.isFinite(Number(anchor?.received_power_dbm)) ? Number(anchor.received_power_dbm) : null, paths: anchor?.ray_paths?.length || 0 };
    }),
  ];
  return (
    <div className="uav-local-scene is-spectrum" aria-label="本地 WebGL 无人机三维视图">
      <div ref={mountRef} className="uav-local-scene-canvas" />
      <div className="uav-scene-hud top-left">LOCAL WEBGL · 城市街区 · {connection === "online" ? "LIVE" : connection === "connecting" ? "CONNECTING" : "RECONNECTING"}</div>
      {spectrumSituation && <div className="uav-scene-hud top-right spectrum">SIONNA RT · {spectrumSituation.computing ? "GPU 计算中" : `${pathCount} 条真实路径`}</div>}
      {controlOverlay}
      <div className="uav-spectrum-link-dock" aria-label="实时频谱态势与链路选择">
        {linkCards.map((link) => (
          <button key={link.id} type="button" className={selectedTransmitter === link.id ? "is-active" : ""} aria-pressed={selectedTransmitter === link.id} onClick={() => onSelectTransmitter?.(link.id)}>
            <span>{link.label}</span>
            <strong>{link.powerDbm == null ? "等待采样" : `${link.powerDbm.toFixed(1)} dBm`}</strong>
            <small>{link.id === "all" ? `ENU ${position}` : `${link.paths} 条传播路径`}</small>
          </button>
        ))}
      </div>
    </div>
  );
}
