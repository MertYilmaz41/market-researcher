// 3D opportunity map: one sphere per game.
//   x = demand, y = dissatisfaction (review-bomb adjusted), z = fixability
//   size = estimated gross revenue (log), color = opportunity score (blue -> teal -> gold)
// Colors come from style.css :root via palette.js.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "three/addons/renderers/CSS2DRenderer.js";
import * as palette from "/static/palette.js";

const HALF = 5;      // x/z span: -5..5
const HEIGHT = 8;    // y span: 0..8
const CENTER = new THREE.Vector3(0, HEIGHT * 0.4, 0);

const color = (name) => new THREE.Color(palette.cssVar(name));

export function scoreColor(score) {
  return new THREE.Color(palette.scoreColor(score));
}

function position(game) {
  const o = game.opportunity;
  const fix = Math.max(0, Math.min(1, (o.fixability - 0.5) / 0.5)); // 0.5 is the "unknown" default
  return new THREE.Vector3(
    -HALF + o.demand * 2 * HALF,
    o.dissatisfaction * HEIGHT,
    HALF - fix * 2 * HALF,
  );
}

function label(text, cls = "axis-label") {
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = text;
  return new CSS2DObject(el);
}

export function createMap(container, { onSelect }) {
  const tooltip = container.querySelector("#tooltip");
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  } catch (e) {
    return { setGames() {}, select() {}, setVisible() {}, available: false }; // no WebGL: app.js falls back to 2D
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  container.prepend(renderer.domElement);

  const labels = new CSS2DRenderer();
  Object.assign(labels.domElement.style, { position: "absolute", inset: "0", pointerEvents: "none" });
  container.append(labels.domElement);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(color("--bg"), 22, 45);
  const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 200);
  camera.position.set(11, 9, 13);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.copy(CENTER);
  controls.enableDamping = true;
  controls.autoRotate = true;
  controls.autoRotateSpeed = 0.6;
  controls.minDistance = 6;
  controls.maxDistance = 35;
  let idleTimer;
  controls.addEventListener("start", () => { controls.autoRotate = false; clearTimeout(idleTimer); });
  controls.addEventListener("end", () => { idleTimer = setTimeout(() => (controls.autoRotate = true), 8000); });

  // Lights
  // neutral warm light: no tint on the score colors
  scene.add(new THREE.HemisphereLight(0xfff3e0, 0x14110c, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(6, 12, 8);
  scene.add(key);

  // Floor grid + bounding box + axes
  const grid = new THREE.GridHelper(HALF * 2, 10, color("--line").offsetHSL(0, 0, 0.08), color("--line"));
  scene.add(grid);
  const box = new THREE.LineSegments(
    new THREE.EdgesGeometry(new THREE.BoxGeometry(HALF * 2, HEIGHT, HALF * 2)),
    new THREE.LineBasicMaterial({ color: color("--line"), transparent: true, opacity: 0.8 }),
  );
  box.position.y = HEIGHT / 2;
  scene.add(box);

  const axisMat = (c) => new THREE.LineBasicMaterial({ color: c });
  const origin = new THREE.Vector3(-HALF, 0, HALF);
  const axes = [
    [new THREE.Vector3(HALF, 0, HALF), color("--accent"), "Demand →", new THREE.Vector3(HALF + 0.6, 0, HALF + 0.6)],
    [new THREE.Vector3(-HALF, HEIGHT, HALF), color("--accent-2"), "Dissatisfaction ↑", new THREE.Vector3(-HALF, HEIGHT + 0.6, HALF)],
    [new THREE.Vector3(-HALF, 0, -HALF), color("--good"), "Fixability →", new THREE.Vector3(-HALF - 0.6, 0, -HALF - 0.6)],
  ];
  for (const [end, color, text, at] of axes) {
    scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([origin, end]), axisMat(color)));
    const l = label(text);
    l.position.copy(at);
    scene.add(l);
  }

  // Selection ring (billboarded each frame)
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1, 1.12, 64),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, side: THREE.DoubleSide }),
  );
  ring.visible = false;
  scene.add(ring);
  // Style via a class: assigning style.cssText would wipe the position:absolute CSS2DObject relies on.
  const nameTag = label("", "name-tag");
  nameTag.visible = false;
  scene.add(nameTag);

  const group = new THREE.Group();
  scene.add(group);
  let spheres = [];       // meshes, userData.game
  let selected = null;
  let born = 0;           // spawn animation start
  const targetGoal = CENTER.clone();

  function clear() {
    for (const obj of [...group.children]) {
      obj.geometry?.dispose();
      obj.material?.dispose();
      group.remove(obj);
    }
    spheres = [];
    selected = null;
    ring.visible = nameTag.visible = false;
  }

  function setGames(games) {
    clear();
    container.querySelector("#map-empty").hidden = games.length > 0;
    const grosses = games.map((g) => Math.log10(Math.max(1, g.box.gross_mid)));
    const lo = Math.min(...grosses), hi = Math.max(...grosses);
    games.forEach((game, i) => {
      const p = position(game);
      const t = hi > lo ? (grosses[i] - lo) / (hi - lo) : 0.5;
      const r = 0.28 + 0.55 * t;
      const color = scoreColor(game.opportunity.score);
      const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(r, 40, 24),
        new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: 0.25, roughness: 0.35, metalness: 0.1 }),
      );
      mesh.position.copy(p);
      mesh.scale.setScalar(0.001);
      mesh.userData = { game, radius: r, delay: i * 60 };
      group.add(mesh);
      spheres.push(mesh);

      // drop line to the floor for depth perception
      const drop = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([p, new THREE.Vector3(p.x, 0, p.z)]),
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.25 }),
      );
      group.add(drop);
    });
    born = performance.now();
    targetGoal.copy(CENTER);
  }

  function select(appid, { focus = true } = {}) {
    selected = spheres.find((s) => s.userData.game.game.appid === appid) || null;
    ring.visible = nameTag.visible = !!selected;
    if (!selected) return;
    ring.position.copy(selected.position);
    ring.scale.setScalar(selected.userData.radius * 1.35);
    nameTag.element.textContent = selected.userData.game.game.name;
    nameTag.position.copy(selected.position).add(new THREE.Vector3(0, selected.userData.radius + 0.5, 0));
    if (focus) targetGoal.copy(selected.position).lerp(CENTER, 0.5);
  }

  // Picking
  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  function pick(event) {
    const rect = renderer.domElement.getBoundingClientRect();
    pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(spheres, false)[0];
    return { hit: hit?.object || null, x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  renderer.domElement.addEventListener("pointermove", (e) => {
    const { hit, x, y } = pick(e);
    renderer.domElement.style.cursor = hit ? "pointer" : "grab";
    if (!hit) { tooltip.hidden = true; return; }
    const g = hit.userData.game;
    tooltip.replaceChildren();
    const b = document.createElement("b");
    b.textContent = g.game.name;
    const s = document.createElement("span");
    s.textContent = `Score ${Math.round(g.opportunity.score)} · ${g.reviews.toLocaleString("en-US")} reviews · ${Math.round(g.rating)}% pos`;
    tooltip.append(b, s);
    tooltip.style.left = `${x}px`;
    tooltip.style.top = `${y}px`;
    tooltip.hidden = false;
  });
  renderer.domElement.addEventListener("pointerleave", () => (tooltip.hidden = true));

  let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => (down = { x: e.clientX, y: e.clientY }));
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) return; // it was a drag
    const { hit } = pick(e);
    if (hit) {
      select(hit.userData.game.game.appid);
      onSelect(hit.userData.game.game.appid);
    }
  });

  // Resize
  function resize() {
    const { clientWidth: w, clientHeight: h } = container;
    renderer.setSize(w, h);
    labels.setSize(w, h);
    camera.aspect = w / Math.max(1, h);
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(container);
  resize();

  // Loop
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  let visible = true;
  function setVisible(on) {
    visible = on;
    renderer.domElement.style.display = labels.domElement.style.display = on ? "" : "none";
    if (on) resize();
  }

  renderer.setAnimationLoop((now) => {
    if (!visible) return; // hidden behind the 2D view: don't burn GPU
    for (const s of spheres) {
      const t = Math.min(1, Math.max(0, (now - born - s.userData.delay) / 600));
      const pulse = s === selected ? 1 + 0.06 * Math.sin(now / 250) : 1;
      s.scale.setScalar(Math.max(0.001, ease(t)) * pulse);
    }
    controls.target.lerp(targetGoal, 0.08);
    if (ring.visible) ring.lookAt(camera.position);
    controls.update();
    renderer.render(scene, camera);
    labels.render(scene, camera);
  });

  return { setGames, select, setVisible, available: true };
}
