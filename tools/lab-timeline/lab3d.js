/* Lab 3D — a arquitetura como máquina física.
   Three.js r158 self-hosted; orbit com arrastar/rodinha, clique drilldown.
   Nenhum número inventado: stages/parts vêm de index.html (checkpoints). */
(function () {
  'use strict';
  const T = window.THREE;
  const host = document.getElementById('lab3dCanvas');
  if (!T || !host) { if (host) host.textContent = 'Three.js não carregado'; return; }

  let W = Math.max(640, host.clientWidth), H = 430;
  const scene = new T.Scene();
  scene.background = new T.Color(0x0d1117);
  scene.fog = new T.Fog(0x0d1117, 26, 52);
  const camera = new T.PerspectiveCamera(46, W / H, 0.1, 200);
  let renderer;
  try { renderer = new T.WebGLRenderer({ antialias: true }); }
  catch (e) { host.textContent = 'WebGL indisponível: ' + e.message; return; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(W, H);
  host.appendChild(renderer.domElement);

  scene.add(new T.AmbientLight(0xffffff, 0.55));
  const key = new T.DirectionalLight(0xffffff, 0.9); key.position.set(6, 12, 9); scene.add(key);
  const rim = new T.DirectionalLight(0x79c0ff, 0.5); rim.position.set(-8, 5, -7); scene.add(rim);

  const machine = new T.Group(); scene.add(machine);
  const COL = { in: 0x1f6feb, loop: 0x8957e5, out: 0x238636, head: 0xd29922, mem: 0x6e7681, flow: 0xf0883e };
  const pickables = [];

  // órbita mínima (sem examples/js, que não existe no r158)
  let theta = 0.34, phi = 1.02, radius = 22, dragging = false, moved = 0, px = 0, py = 0;
  function updateCam() {
    camera.position.set(radius * Math.sin(phi) * Math.sin(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.cos(theta));
    camera.lookAt(0, 0.4, 0);
  }
  updateCam();
  host.addEventListener('pointerdown', e => { dragging = true; moved = 0; px = e.clientX; py = e.clientY; });
  window.addEventListener('pointerup', () => { dragging = false; });
  window.addEventListener('pointermove', e => {
    if (!dragging) return;
    const dx = e.clientX - px, dy = e.clientY - py; px = e.clientX; py = e.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    theta -= dx * 0.006; phi = Math.min(1.5, Math.max(0.35, phi - dy * 0.005)); updateCam();
  });
  host.addEventListener('wheel', e => { e.preventDefault(); radius = Math.min(34, Math.max(11, radius + e.deltaY * 0.02)); updateCam(); }, { passive: false });

  function disposeGroup(g) {
    while (g.children.length) {
      const c = g.children.pop();
      c.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) { if (o.material.map) o.material.map.dispose(); o.material.dispose(); } });
    }
    pickables.length = 0;
  }
  function mesh(x, y, z, w, h, d, color, part, opacity) {
    const m = new T.Mesh(new T.BoxGeometry(w, h, d),
      new T.MeshStandardMaterial({ color: color, roughness: 0.55, metalness: 0.12, transparent: !!opacity, opacity: opacity || 1 }));
    m.position.set(x, y, z);
    if (part) { m.userData.part = part; pickables.push(m); }
    machine.add(m);
    return m;
  }
  function shell(x, y, z, w, h, d, color, part) {
    const m = mesh(x, y, z, w, h, d, color, part, 0.22);
    const e = new T.LineSegments(new T.EdgesGeometry(m.geometry), new T.LineBasicMaterial({ color: 0xc9d1d9 }));
    m.add(e); return m;
  }
  function label(text, x, y, z, color) {
    const c = document.createElement('canvas'); c.width = 384; c.height = 96;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(13,17,23,0.82)'; g.fillRect(0, 0, 384, 96);
    g.strokeStyle = color || '#c9d1d9'; g.lineWidth = 4; g.strokeRect(2, 2, 380, 92);
    g.fillStyle = '#e6edf3'; g.font = 'bold 30px system-ui'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, 192, 50, 360);
    const sp = new T.Sprite(new T.SpriteMaterial({ map: new T.CanvasTexture(c), transparent: true, depthTest: false }));
    sp.position.set(x, y, z); sp.scale.set(2.5, 0.62, 1); machine.add(sp); return sp;
  }
  function arrow(from, to, color, part) {
    const a = new T.Vector3().fromArray(from), b = new T.Vector3().fromArray(to);
    const dir = new T.Vector3().subVectors(b, a), len = dir.length();
    if (len < 0.05) return;
    const mat = new T.MeshStandardMaterial({ color: color || 0x8b949e, roughness: 0.6 });
    const shaft = new T.Mesh(new T.CylinderGeometry(0.055, 0.055, len - 0.32, 8), mat);
    shaft.position.copy(a).add(b).multiplyScalar(0.5);
    shaft.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), dir.clone().normalize());
    if (part) { shaft.userData.part = part; pickables.push(shaft); }
    machine.add(shaft);
    const head = new T.Mesh(new T.ConeGeometry(0.18, 0.38, 10), mat);
    head.position.copy(b).sub(dir.clone().normalize().multiplyScalar(0.19));
    head.quaternion.copy(shaft.quaternion); machine.add(head);
  }
  function loopRibbon(cx, color) {
    const pts = [];
    for (let i = 0; i <= 28; i++) {
      const t = i / 28;
      pts.push(new T.Vector3(cx + 2.4 * Math.cos(Math.PI * t), 1.15 - 1.9 * Math.sin(Math.PI * t), 1.9));
    }
    const curve = new T.CatmullRomCurve3(pts);
    const tube = new T.Mesh(new T.TubeGeometry(curve, 40, 0.06, 8, false),
      new T.MeshStandardMaterial({ color: color, roughness: 0.5 }));
    tube.userData.part = 'loop'; pickables.push(tube); machine.add(tube);
    label('ι 0→3  pesos compartilhados', cx, -0.4, 2.1, '#f0883e');
  }

  function build(stage) {
    disposeGroup(machine);
    const d = stage.d, scale = 0.55 + 0.45 * (d / 1216);
    const yy = 1.1;
    // base
    mesh(0, -0.55, 0, 20, 0.35, 5.2, 0x21262d);
    for (let i = -9; i <= 9; i += 3) mesh(i, -0.36, 0, 0.02, 0.02, 5, 0x30363d);
    // token -> embedding -> position
    for (let i = 0; i < 3; i++) mesh(-9 + i * 0.42, yy, 1.5, 0.3, 0.7 * scale, 0.3, COL.in, 'token');
    label('token id', -8.6, yy + 1.0, 1.5, '#1f6feb');
    for (let i = 0; i < 6; i++) mesh(-7.2, yy, -0.8 + i * 0.32, 1.1, 0.26, 0.24, COL.in, 'embed', 0.72);
    label('embedding ' + stage.d, -7.2, yy + 1.0, 0.5, '#1f6feb');
    for (let i = 0; i < 4; i++) mesh(-5.1, yy, -0.5 + i * 0.3, 0.85, 0.24, 0.22, COL.in, 'pos', 0.75);
    label('+ posição', -5.1, yy + 1.0, 0.6, '#1f6feb');
    arrow([-8.6, yy, 1.5], [-7.7, yy, 1.2], 0x8b949e);
    arrow([-6.6, yy, 0.6], [-5.6, yy, 0.6], 0x8b949e);
    // blocos de entrada
    const bx = [-3.7, -2.1];
    bx.forEach((x, k) => {
      const part = k === 0 ? 'b0' : 'b1';
      shell(x, yy, 0, 1.3, 1.7 * scale, 1.5, k === 0 ? COL.in : COL.loop, part);
      mesh(x, yy + 0.35 * scale, 0, 0.9, 0.22, 1.2, 0xc9d1d9, 'ln1', 0.85);
      mesh(x, yy - 0.1 * scale, 0, 0.9, 0.34, 1.2, COL.loop, 'attn', 0.9);
      mesh(x, yy - 0.55 * scale, 0, 0.9, 0.28, 1.2, COL.flow, 'res1', 0.9);
      label(k === 0 ? 'B0 entra' : 'B1 β=0,05', x, yy + 1.35 * scale, 0, k === 0 ? '#79c0ff' : '#d2a8ff');
    });
    if (window.MACH_PARTS && window.MACH_PARTS.beta) label('β·FFN', -2.1, yy - 1.25 * scale, 0, '#f0883e');
    // cartucho recorrente (caixa transparente com 4 cópias internas)
    shell(0.4, yy, 0, 2.9, 1.9 * scale, 1.9, COL.loop, 'loop');
    for (let i = 0; i < 4; i++) {
      const x = -0.55 + i * 0.62;
      mesh(x, yy + 0.42 * scale, 0, 0.42, 0.22, 1.35, 0xc9d1d9, 'ln1', 0.9);
      mesh(x, yy - 0.02 * scale, 0, 0.42, 0.36, 1.35, COL.loop, 'attn', 0.92);
      mesh(x, yy - 0.52 * scale, 0, 0.42, 0.28, 1.35, COL.flow, 'ffn', 0.92);
      arrow([x, yy + 0.3 * scale, 0.75], [x, yy - 0.3 * scale, 0.75], 0xd2a8ff);
    }
    label('B2–B5  bloco único ×4', 0.4, yy + 1.45 * scale, 0.9, '#d2a8ff');
    loopRibbon(0.4, 0xf0883e);
    // saída
    shell(2.8, yy, 0, 1.6, 1.7 * scale, 1.5, COL.out, 'b67');
    mesh(2.8, yy + 0.3 * scale, 0, 1.0, 0.3, 1.15, COL.out, 'ln2', 0.85);
    mesh(2.8, yy - 0.4 * scale, 0, 1.0, 0.3, 1.15, COL.out, 'res2', 0.85);
    label('B6–B7 saída', 2.8, yy + 1.35 * scale, 0, '#56d364');
    shell(4.3, yy, 0, 0.85, 1.5 * scale, 1.2, COL.out, 'lnfinal');
    label('LN final', 4.3, yy + 1.15 * scale, 0, '#56d364');
    // cabeça e logits
    mesh(5.6, yy, 0, 1.0, 1.5 * scale, 1.2, COL.head, 'head', 0.82);
    label('head ' + d + '→10k', 5.6, yy + 1.2 * scale, 0, '#e3b341');
    for (let i = 0; i < 8; i++) {
      const hgt = 0.35 + 0.55 * ((i * 7 % 9) / 9);
      mesh(7.2, yy - 0.6 + hgt / 2, -0.8 + i * 0.23, 0.16, hgt, 0.16, COL.head, 'logits', 0.9);
    }
    label('logits → token', 7.3, yy + 1.1, 0, '#e3b341');
    // fluxo principal
    arrow([-3.0, yy, 0], [-2.8, yy, 0], 0x8b949e);
    arrow([-1.4, yy, 0], [-1.1, yy, 0], 0x8b949e);
    arrow([1.9, yy, 0], [2.0, yy, 0], 0x8b949e);
    arrow([3.6, yy, 0], [3.85, yy, 0], 0x8b949e);
    arrow([4.75, yy, 0], [5.1, yy, 0], 0x8b949e);
    arrow([6.1, yy, 0], [7.0, yy, 0], 0x8b949e);
    // memória KV (armazenamento)
    for (let i = 0; i < 4; i++) mesh(1.0 + i * 0.08, -1.5, 3.35 - i * 0.42, 3.0, 0.16, 0.32, COL.mem, 'kv', 0.9);
    label('KV cache — onde fica guardado', 2.2, -2.05, 3.4, '#adb7c2');
    arrow([0.4, yy - 0.9, 0.9], [1.4, -1.45, 3.0], 0x6e7681, 'kv');
    arrow([2.6, -1.45, 3.0], [2.4, yy - 0.9, 0.9], 0x6e7681, 'kv');
    // legenda de escala
    label('d=' + d + ' · heads=8 · head_dim=' + Math.round(d / 8) + ' · FFN=' + (4 * d) + ' · ' + stage.params + 'M params', 0, -2.45, -1.2, '#8b949e');
  }

  const stages = window.MACH_STAGES || [];
  const slider = document.getElementById('lab3dStage');
  const out = document.getElementById('lab3dStageLabel');
  let idx = Math.max(0, stages.length - 1);
  if (slider) { slider.max = Math.max(0, stages.length - 1); slider.value = idx; }
  function showStage(i) {
    idx = i;
    if (!stages.length) return;
    const s = stages[i];
    build(s);
    if (out) out.textContent = s.date + ' · ' + s.label + ' · val=' + (s.val === null ? 'não medido' : s.val);
    if (window.machDetail) window.machDetail('loop', s);
  }
  if (slider) slider.addEventListener('input', e => showStage(parseInt(e.target.value, 10)));

  const ray = new T.Raycaster(), mouse = new T.Vector2();
  host.addEventListener('click', e => {
    if (moved > 6) return;
    const r = renderer.domElement.getBoundingClientRect();
    mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    ray.setFromCamera(mouse, camera);
    const hit = ray.intersectObjects(pickables, false)[0];
    if (hit && hit.object.userData.part && window.machDetail && stages[idx]) {
      window.machDetail(hit.object.userData.part, stages[idx]);
    }
  });
  window.addEventListener('resize', () => {
    W = Math.max(640, host.clientWidth); camera.aspect = W / H; camera.updateProjectionMatrix(); renderer.setSize(W, H);
  });
  function frame() { requestAnimationFrame(frame); machine.rotation.y = Math.sin(Date.now() / 9000) * 0.035; renderer.render(scene, camera); }
  showStage(idx);
  frame();
  window.lab3d = { showStage: showStage, count: () => pickables.length };
})();
