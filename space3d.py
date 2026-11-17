"""space3d.py - a real-time 3D space background for Streamlit (no libraries, plain WebGL).

What you see:
  * ~10,000 stars on a slowly turning sky, with a Milky Way band, twinkling at different speeds
  * ~1,200 nearby stars that stream past you, so the space feels endless
  * a gas giant with rings (rings cast a shadow on the planet and the planet shadows the rings)
  * an ocean world with clouds, an atmosphere glow and city lights on its night side
  * mouse and scroll parallax

How it works (for your viva): Streamlit can't run JavaScript in normal text, so we put the scene in a
tiny iframe (st.components.v1.html). The iframe's own JavaScript then stretches the iframe over the whole
screen, sends it behind the page and makes it click-through. Planets are drawn by a GPU shader that
computes the lighting of a sphere for every pixel (like a tiny ray tracer).

Use:  from space3d import render_space_3d      then call   render_space_3d()   once, before your tabs.
If the browser has no WebGL, nothing happens and your normal CSS stars stay.
"""

import streamlit.components.v1 as components

SPACE_3D_HTML = r"""<!doctype html>
<html><head><meta charset="utf-8">
<style>html,body{margin:0;padding:0;background:transparent;overflow:hidden}canvas{display:block}</style>
</head><body>
<script>
(function () {
  'use strict';

  /* ---------- 1. turn this iframe into a full-screen, click-through background ---------- */
  var P = null, FE = null;
  try { P = window.parent; FE = window.frameElement; } catch (e) {}
  if (FE && P) {
    try {
      FE.style.cssText = 'position:fixed;top:0;left:0;width:100vw;height:100vh;border:0;z-index:-1;pointer-events:none;background:transparent;';
      var box = FE.closest('[data-testid="stElementContainer"],.element-container');
      if (box) box.style.cssText += ';position:absolute;width:0;height:0;margin:0;padding:0;overflow:visible;';
      // anything that would trap a position:fixed child inside its own box gets switched off
      for (var el = FE.parentElement; el && el !== P.document.body; el = el.parentElement) {
        var cs = P.getComputedStyle(el);
        if (cs.transform && cs.transform !== 'none') el.style.transform = 'none';
        if (cs.filter && cs.filter !== 'none') el.style.filter = 'none';
        if (cs.backdropFilter && cs.backdropFilter !== 'none') el.style.backdropFilter = 'none';
        if (cs.perspective && cs.perspective !== 'none') el.style.perspective = 'none';
        if (cs.contain && cs.contain !== 'none' && cs.contain !== 'style') el.style.contain = 'none';
        if (cs.willChange && /transform|filter|perspective/.test(cs.willChange)) el.style.willChange = 'auto';
      }
      // same colour scheme as the page, otherwise the browser paints the iframe with an opaque background
      document.documentElement.style.colorScheme = P.getComputedStyle(FE).colorScheme || 'normal';
    } catch (e) {}
  }

  /* ---------- 2. WebGL set-up ---------- */
  var canvas = document.createElement('canvas');
  canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%';
  document.body.appendChild(canvas);
  var gl = canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: false, powerPreference: 'high-performance' });
  if (!gl) { canvas.remove(); return; }                         // no WebGL: leave the CSS stars alone
  try { if (P) P.document.documentElement.classList.add('gl-on'); } catch (e) {}   // tells the page CSS to hide its 2D stars

  function compile(type, src) {
    var s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) { console.error(gl.getShaderInfoLog(s)); return null; }
    return s;
  }
  function program(vs, fs) {
    var p = gl.createProgram(), a = compile(gl.VERTEX_SHADER, vs), b = compile(gl.FRAGMENT_SHADER, fs);
    if (!a || !b) return null;
    gl.attachShader(p, a); gl.attachShader(p, b); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) { console.error(gl.getProgramInfoLog(p)); return null; }
    return p;
  }

  /* ---------- 3. stars ---------- */
  var STAR_VS = [
    'attribute vec3 aPos; attribute vec4 aData; attribute vec3 aColor;',
    'uniform mat3 uRot; uniform float uTime, uAspect, uTan, uMode, uPx, uSpeed, uMaxPt;',
    'varying vec3 vColor; varying float vA; varying float vSpike;',
    'void main(){',
    '  vec3 p = aPos; float fade = 1.0;',
    '  if (uMode > 0.5) {',                                         // near layer: flies toward you, wraps around = endless
    '    float L = 60.0;',
    '    p.z = mod(p.z + uTime*uSpeed, L) - L;',
    '    float t = (p.z + L) / L;',
    '    fade = smoothstep(0.0, 0.12, t) * (1.0 - smoothstep(0.9, 1.0, t));',
    '  } else { p = normalize(p) * 50.0; }',                        // far layer: the "celestial sphere"
    '  vec3 v = uRot * p;',
    '  if (v.z > -0.1) { gl_Position = vec4(2.0,2.0,2.0,1.0); gl_PointSize = 0.0; vA = 0.0; vColor = vec3(0.0); vSpike = 0.0; return; }',
    '  gl_Position = vec4((v.x / -v.z) / (uTan * uAspect), (v.y / -v.z) / uTan, 0.0, 1.0);',
    '  float tw  = 0.62 + 0.38 * sin(uTime * aData.y + aData.x);',  // two sine waves = irregular twinkle
    '  float tw2 = 0.80 + 0.20 * sin(uTime * aData.y * 2.7 + aData.x * 1.9);',
    '  float size = aData.z;',
    '  if (uMode > 0.5) size *= clamp(14.0 / (-v.z), 0.6, 4.0);',   // nearer stars look bigger
    '  gl_PointSize = min(size * uPx, uMaxPt);',
    '  vSpike = (aData.z > 5.0 && aData.z < 20.0) ? 1.0 : 0.0;',
    '  vColor = aColor; vA = aData.w * tw * tw2 * fade;',
    '}'
  ].join('\n');

  var STAR_FS = [
    'precision mediump float;',
    'varying vec3 vColor; varying float vA; varying float vSpike;',
    'void main(){',
    '  vec2 c = (gl_PointCoord - 0.5) * 2.0;',
    '  float d = length(c);',
    '  float a = pow(max(1.0 - d, 0.0), 3.0) + 0.6 * smoothstep(0.45, 0.0, d);',
    '  if (vSpike > 0.5) a += 0.55 * (exp(-abs(c.x) * 30.0) * exp(-abs(c.y) * 2.5) + exp(-abs(c.y) * 30.0) * exp(-abs(c.x) * 2.5));',
    '  a *= vA;',
    '  gl_FragColor = vec4(vColor * a, a);',
    '}'
  ].join('\n');

  var starProg = program(STAR_VS, STAR_FS);
  if (!starProg) { canvas.remove(); return; }

  function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  var rand = mulberry32(20261117);
  function gauss() { return Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(6.2831853 * rand()); }
  function norm3(v) { var l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
  function cross3(a, b) { return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]; }

  var PALETTE = [[1, 1, 1], [1, 1, 1], [1, 1, 1], [0.78, 0.86, 1.0], [1.0, 0.92, 0.78], [0.86, 0.72, 1.0], [0.8, 0.6, 1.0]];
  function pickColor() { return PALETTE[Math.floor(rand() * PALETTE.length)]; }

  var STRIDE = 10;   // floats per star: pos(3) data(4) colour(3)
  function pushStar(arr, pos, phase, freq, size, bright, col) {
    arr.push(pos[0], pos[1], pos[2], phase, freq, size, bright, col[0], col[1], col[2]);
  }

  // far sky: a Milky Way band (dense) plus an even scatter
  var bandN = norm3([0.35, 0.82, 0.45]), e1 = norm3(cross3(bandN, [0, 0, 1])), e2 = cross3(bandN, e1);
  var far = [];
  var i, k;
  for (i = 0; i < 110000; i++) {
    var dir, inBand = i < 62000;
    if (inBand) {
      var th = rand() * 6.2831853, lat = gauss() * 0.16;
      dir = norm3([Math.cos(th)*e1[0] + Math.sin(th)*e2[0] + lat*bandN[0], Math.cos(th)*e1[1] + Math.sin(th)*e2[1] + lat*bandN[1], Math.cos(th)*e1[2] + Math.sin(th)*e2[2] + lat*bandN[2]]);
    } else {
      dir = norm3([gauss(), gauss(), gauss()]);
    }
    var m = rand(), size = m < 0.975 ? 1.0 + rand() * 1.4 : (m < 0.9975 ? 2.6 + rand() * 1.8 : 6.0 + rand() * 3.0);
    var bright = m < 0.975 ? 0.3 + Math.pow(rand(), 1.5) * 0.9 : 1.0 + rand() * 0.4;
    if (inBand) { bright *= 0.7; }
    pushStar(far, dir, rand() * 6.28, 0.6 + rand() * 3.4, size, bright, pickColor());
  }
  // soft glow blobs along the band = the diffuse haze of the Milky Way and a few nebula clouds
  var haze = [[0.62, 0.42, 1.0], [0.85, 0.80, 1.0], [0.72, 0.38, 0.95], [0.5, 0.45, 1.0]];
  for (i = 0; i < 520; i++) {
    var th2 = rand() * 6.2831853, lat2 = gauss() * 0.10;
    var hd = norm3([Math.cos(th2)*e1[0] + Math.sin(th2)*e2[0] + lat2*bandN[0], Math.cos(th2)*e1[1] + Math.sin(th2)*e2[1] + lat2*bandN[1], Math.cos(th2)*e1[2] + Math.sin(th2)*e2[2] + lat2*bandN[2]]);
    pushStar(far, hd, rand() * 6.28, 0.05 + rand() * 0.1, 80 + rand() * 140, 0.045 + rand() * 0.06, haze[Math.floor(rand() * haze.length)]);
  }
  var near = [];
  for (i = 0; i < 1500; i++) {
    pushStar(near, [(rand() - 0.5) * 80, (rand() - 0.5) * 80, -rand() * 60], rand() * 6.28, 0.8 + rand() * 3.0, 1.2 + rand() * 1.6, 0.5 + rand() * 0.6, pickColor());
  }

  function makeBuffer(arr) { var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(arr), gl.STATIC_DRAW); return { buf: b, count: arr.length / STRIDE }; }
  var farBuf = makeBuffer(far), nearBuf = makeBuffer(near);
  var sU = {}; ['uRot', 'uTime', 'uAspect', 'uTan', 'uMode', 'uPx', 'uSpeed', 'uMaxPt'].forEach(function (n) { sU[n] = gl.getUniformLocation(starProg, n); });
  var sA = { pos: gl.getAttribLocation(starProg, 'aPos'), data: gl.getAttribLocation(starProg, 'aData'), col: gl.getAttribLocation(starProg, 'aColor') };
  var maxPt = gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)[1] || 64;

  function drawStars(b, mode, rot, t, aspect, dpr) {
    gl.useProgram(starProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, b.buf);
    gl.enableVertexAttribArray(sA.pos);  gl.vertexAttribPointer(sA.pos, 3, gl.FLOAT, false, STRIDE * 4, 0);
    gl.enableVertexAttribArray(sA.data); gl.vertexAttribPointer(sA.data, 4, gl.FLOAT, false, STRIDE * 4, 12);
    gl.enableVertexAttribArray(sA.col);  gl.vertexAttribPointer(sA.col, 3, gl.FLOAT, false, STRIDE * 4, 28);
    gl.uniformMatrix3fv(sU.uRot, false, rot);
    gl.uniform1f(sU.uTime, t); gl.uniform1f(sU.uAspect, aspect); gl.uniform1f(sU.uTan, Math.tan(0.5 * 74 * Math.PI / 180));
    gl.uniform1f(sU.uMode, mode); gl.uniform1f(sU.uPx, dpr); gl.uniform1f(sU.uSpeed, 1.1); gl.uniform1f(sU.uMaxPt, maxPt);
    gl.drawArrays(gl.POINTS, 0, b.count);
  }

  /* ---------- 4. planets: one shader that lights a sphere for every pixel ---------- */
  var PLANET_VS = [
    'attribute vec2 aQuad; uniform vec2 uCenter, uRes; uniform float uHalf, uRadius; varying vec2 vUv;',
    'void main(){ vec2 px = uCenter + aQuad * uHalf; gl_Position = vec4(px / uRes * 2.0 - 1.0, 0.0, 1.0); vUv = aQuad * (uHalf / uRadius); }'
  ].join('\n');

  var PLANET_FS = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH', 'precision highp float;', '#else', 'precision mediump float;', '#endif',
    'varying vec2 vUv;',
    'uniform float uType, uTime, uSpin, uRadius, uRingIn, uRingOut;',
    'uniform vec3 uSun, uAxis;',
    // --- noise
    'float hash(vec3 p){ p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }',
    'float noise(vec3 x){ vec3 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);',
    '  return mix(mix(mix(hash(i), hash(i + vec3(1,0,0)), f.x), mix(hash(i + vec3(0,1,0)), hash(i + vec3(1,1,0)), f.x), f.y),',
    '             mix(mix(hash(i + vec3(0,0,1)), hash(i + vec3(1,0,1)), f.x), mix(hash(i + vec3(0,1,1)), hash(i + vec3(1,1,1)), f.x), f.y), f.z); }',
    'float fbm(vec3 p){ float a = 0.5, s = 0.0; for (int i = 0; i < 5; i++) { s += a * noise(p); p = p * 2.03 + vec3(1.7, 9.2, 3.1); a *= 0.5; } return s; }',
    // --- rings: density as a function of radius (in planet radii)
    'float ringDensity(float rr){',
    '  float t = (rr - uRingIn) / (uRingOut - uRingIn);',
    '  if (t < 0.0 || t > 1.0) return 0.0;',
    '  float d = 0.50 + 0.50 * sin(rr * 26.0 + 7.0 * noise(vec3(rr * 7.0, 1.0, 2.0)));',
    '  d *= 0.40 + 0.60 * noise(vec3(rr * 21.0, 3.0, 7.0));',
    '  d *= smoothstep(0.0, 0.05, t) * smoothstep(1.0, 0.9, t);',
    '  d *= 1.0 - 0.93 * smoothstep(0.035, 0.0, abs(t - 0.58));',   // a dark gap, like the Cassini division
    '  d *= 1.0 - 0.6 * smoothstep(0.02, 0.0, abs(t - 0.30));',
    '  return clamp(d * 1.25, 0.0, 1.0);',
    '}',
    'void main(){',
    '  vec2 uv = vUv; float r = length(uv);',
    '  vec3 L = normalize(uSun);',
    '  vec3 A = normalize(uAxis);',
    '  vec3 U = normalize(cross(A, vec3(0.0, 0.0, 1.0))); vec3 V = cross(A, U);',
    '  float cs = cos(uSpin), sn = sin(uSpin);',
    '  vec4 base = vec4(0.0);',
    '  float zs = -10.0;',                                           // depth of the planet surface at this pixel
    // ---------------- the planet body
    '  float cover = clamp((1.0 - r) * uRadius / 1.5, 0.0, 1.0);',
    '  if (cover > 0.0) {',
    '    float z = sqrt(max(1.0 - r * r, 0.0)); zs = z;',
    '    vec3 n = vec3(uv, z);',
    '    float ndl = dot(n, L);',
    '    vec3 loc = vec3(dot(n, U), dot(n, V), dot(n, A));',
    '    loc.xy = mat2(cs, -sn, sn, cs) * loc.xy;',
    '    vec3 col; vec3 atm; float diff;',
    '    if (uType < 0.5) {',
    // ---- gas giant
    '      float lat = loc.z;',
    '      float warp = fbm(vec3(loc.xy * 3.0, lat * 6.0) + 3.7);',
    '      float band = lat * 8.0 + (warp - 0.5) * 1.6 + 0.35 * sin(lat * 19.0);',
    '      float b = 0.5 + 0.5 * sin(band * 3.14159);',
    '      float fine = fbm(vec3(loc.xy * 8.0, lat * 30.0));',
    '      float t = clamp(b * 0.78 + fine * 0.30, 0.0, 1.0);',
    '      vec3 c0 = vec3(0.34, 0.19, 0.62), c1 = vec3(0.56, 0.36, 0.90), c2 = vec3(0.79, 0.64, 1.0), c3 = vec3(0.96, 0.90, 1.0);',
    '      col = mix(c0, c1, smoothstep(0.0, 0.4, t)); col = mix(col, c2, smoothstep(0.3, 0.7, t)); col = mix(col, c3, smoothstep(0.65, 1.0, t));',
    '      float lon = atan(loc.y, loc.x); float dl = mod(lon - 0.9 + 3.14159, 6.28318) - 3.14159;',   // a big storm
    '      float e = length(vec2(dl * 1.0, (lat + 0.34) * 3.0));',
    '      float storm = smoothstep(0.55, 0.0, e);',
    '      float swirl = fbm(vec3(dl * 5.0 + (lat + 0.34) * 3.0, (lat + 0.34) * 9.0, 4.0));',
    '      col = mix(col, mix(vec3(0.95, 0.55, 0.85), vec3(1.0, 0.86, 0.95), swirl), storm * 0.85);',
    '      diff = smoothstep(-0.12, 0.85, ndl);',
    '      col *= 0.42 + 0.58 * pow(z, 0.45);',                      // limb darkening
    '      atm = vec3(0.70, 0.55, 1.0);',
    '      col = col * (0.07 + 1.05 * diff);',
    '      col += atm * pow(1.0 - z, 3.0) * 0.45 * smoothstep(-0.3, 0.7, ndl);',
    // the rings throw a shadow on the planet
    '      float dla = dot(L, A);',
    '      if (abs(dla) > 0.02 && uRingOut > 0.0) { float tt = -dot(n, A) / dla; if (tt > 0.0) { vec3 Pq = n + tt * L; col *= 1.0 - 0.8 * ringDensity(length(Pq)); } }',
    '    } else {',
    // ---- ocean world
    '      float h = fbm(loc * 2.6 + 11.0) + 0.18 * (noise(loc * 9.0) - 0.5);',
    '      float sea = 0.50; float land = smoothstep(sea, sea + 0.014, h);',
    '      vec3 deep = vec3(0.015, 0.03, 0.22), shallow = vec3(0.10, 0.22, 0.66);',
    '      vec3 ocean = mix(deep, shallow, smoothstep(sea - 0.22, sea, h));',
    '      vec3 low = vec3(0.30, 0.30, 0.42), high = vec3(0.64, 0.58, 0.72);',
    '      vec3 ground = mix(low, high, smoothstep(sea, sea + 0.28, h)) * (0.8 + 0.4 * noise(loc * 24.0));',
    '      float polar = smoothstep(0.80, 0.93, abs(loc.z) + (fbm(loc * 5.0) - 0.5) * 0.3);',
    '      ground = mix(ground, vec3(0.95, 0.96, 1.0), polar); ocean = mix(ocean, vec3(0.86, 0.9, 1.0), polar * 0.9);',
    '      vec3 loc2 = vec3(dot(n, U), dot(n, V), dot(n, A)); float cs2 = cos(uSpin * 1.45), sn2 = sin(uSpin * 1.45); loc2.xy = mat2(cs2, -sn2, sn2, cs2) * loc2.xy;',
    '      float cl = fbm(loc2 * vec3(3.2, 3.2, 5.2) + fbm(loc2 * 2.0 + 4.0) * 1.3);',
    '      float cloud = smoothstep(0.50, 0.78, cl);',
    '      float landF = land * (1.0 - polar * 0.0);',
    '      vec3 surf = mix(ocean, ground, landF);',
    '      surf = mix(surf, vec3(1.0), cloud * 0.92);',
    '      diff = smoothstep(-0.02, 0.45, ndl) * 0.35 + max(ndl, 0.0) * 0.75;',
    '      vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));',
    '      float spec = pow(max(dot(n, H), 0.0), 80.0) * (1.0 - landF) * (1.0 - cloud) * (1.0 - polar);',
    '      col = surf * (0.02 + diff) + vec3(1.0, 0.95, 1.0) * spec * 0.9;',
    '      float night = smoothstep(0.08, -0.18, ndl);',
    '      if (night > 0.01) { float cityN = fbm(loc * 34.0); float city = smoothstep(0.60, 0.74, cityN) * landF * (1.0 - polar) * night * (1.0 - cloud * 0.85); col += vec3(1.0, 0.72, 0.38) * city * 0.95; }',
    '      atm = vec3(0.55, 0.55, 1.0);',
    '      float lit = smoothstep(-0.35, 0.65, ndl);',
    '      col += atm * pow(1.0 - z, 3.0) * (0.15 + 0.95 * lit);',
    '      col += vec3(0.85, 0.45, 1.0) * exp(-pow(ndl * 6.0, 2.0)) * pow(1.0 - z, 1.6) * 0.5;',   // twilight band at the day/night line
    '    }',
    '    base = vec4(col * cover, cover);',
    '  }',
    // ---------------- atmosphere halo just outside the disc
    '  if (r >= 1.0) {',
    '    float hgt = (uType < 0.5) ? 0.07 : 0.14;',
    '    float h = clamp((r - 1.0) / hgt, 0.0, 1.0);',
    '    float glow = pow(1.0 - h, 3.0);',
    '    float lit = smoothstep(-0.6, 0.8, dot(normalize(uv), normalize(L.xy + 1e-4)));',
    '    vec3 atmC = (uType < 0.5) ? vec3(0.70, 0.55, 1.0) : vec3(0.55, 0.60, 1.0);',
    '    float ga = glow * (0.08 + 0.55 * lit) * ((uType < 0.5) ? 0.55 : 1.0);',
    '    base = vec4(atmC * ga, ga);',
    '  }',
    // ---------------- rings, in front of or behind the planet
    '  if (uRingOut > 0.0 && abs(A.z) > 0.02) {',
    '    float zr = -(uv.x * A.x + uv.y * A.y) / A.z;',
    '    vec3 Pr = vec3(uv, zr);',
    '    float rr = length(Pr);',
    '    float dens = ringDensity(rr);',
    '    if (dens > 0.001) {',
    '      bool front = zr > zs;',
    '      if (front || r >= 1.0) {',
    '        float tl = -dot(Pr, L); float shadow = 1.0;',
    '        if (tl > 0.0) { float d2 = dot(Pr, Pr) - tl * tl; shadow = smoothstep(0.90, 1.04, sqrt(max(d2, 0.0))); }',
    '        vec3 rc = vec3(0.95, 0.84, 1.0) * (0.55 + 0.55 * noise(vec3(rr * 18.0, 5.0, 1.0)));',
    '        rc *= (0.50 + 0.85 * abs(dot(A, L))) * mix(0.05, 1.0, shadow);',
    '        float ra = dens * 0.9;',
    '        vec4 ring = vec4(rc * ra, ra);',
    '        base = ring + base * (1.0 - ring.a);',
    '      }',
    '    }',
    '  }',
    '  gl_FragColor = base;',
    '}'
  ].join('\n');

  var planetProg = program(PLANET_VS, PLANET_FS);
  var quad = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  var pU = {};
  if (planetProg) ['uCenter', 'uRes', 'uHalf', 'uRadius', 'uType', 'uTime', 'uSpin', 'uSun', 'uAxis', 'uRingIn', 'uRingOut'].forEach(function (n) { pU[n] = gl.getUniformLocation(planetProg, n); });
  var pQuad = planetProg ? gl.getAttribLocation(planetProg, 'aQuad') : -1;

  function axisFrom(roll, elev) { return [-Math.sin(roll) * Math.cos(elev), Math.cos(roll) * Math.cos(elev), Math.sin(elev)]; }
  var SUN = [-0.62, 0.38, 0.68];
  var PLANETS = [
    // ocean world, small and "far": lower left (y counts from the top)
    { type: 1, x: 0.09, y: 0.80, size: 0.13, depth: 0.5, spinRate: 0.045, axis: axisFrom(0.40, 0.42), ring: false },
    // gas giant with rings, big and "near": upper right
    { type: 0, x: 0.80, y: 0.21, size: 0.19, depth: 1.0, spinRate: 0.030, axis: axisFrom(-0.36, 0.40), ring: true }
  ];

  function drawPlanet(p, t, W, H, mx, my, sc) {
    if (!planetProg) return;
    var portrait = H > W;
    var base = Math.min(W, H);
    var radius = p.size * base * (portrait ? 1.0 : 1.05);
    var cx = p.x * W + (Math.sin(t * 0.05 + p.x * 9.0) * 7 - mx * 26 * p.depth) * (W / 1400 + 0.4);
    var cy = (1 - p.y) * H + (Math.cos(t * 0.04 + p.y * 7.0) * 6 + my * 18 * p.depth) + sc * 70 * p.depth;
    var half = radius * (p.ring ? 2.6 : 1.3);
    gl.useProgram(planetProg);
    gl.bindBuffer(gl.ARRAY_BUFFER, quad);
    gl.enableVertexAttribArray(pQuad); gl.vertexAttribPointer(pQuad, 2, gl.FLOAT, false, 0, 0);
    gl.uniform2f(pU.uCenter, cx, cy); gl.uniform2f(pU.uRes, W, H);
    gl.uniform1f(pU.uHalf, half); gl.uniform1f(pU.uRadius, radius);
    gl.uniform1f(pU.uType, p.type); gl.uniform1f(pU.uTime, t); gl.uniform1f(pU.uSpin, t * p.spinRate);
    gl.uniform3f(pU.uSun, SUN[0], SUN[1], SUN[2]); gl.uniform3f(pU.uAxis, p.axis[0], p.axis[1], p.axis[2]);
    gl.uniform1f(pU.uRingIn, p.ring ? 1.38 : 0.0); gl.uniform1f(pU.uRingOut, p.ring ? 2.35 : 0.0);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
  }

  /* ---------- 5. camera, input, render loop ---------- */
  function mul3(a, b) { var r = [], i, j, k; for (i = 0; i < 3; i++) for (j = 0; j < 3; j++) { var s = 0; for (k = 0; k < 3; k++) s += a[i*3+k] * b[k*3+j]; r.push(s); } return r; }
  function rotMat(yaw, pitch, roll) {
    var cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), cr = Math.cos(roll), sr = Math.sin(roll);
    var m = mul3([cr, -sr, 0, sr, cr, 0, 0, 0, 1], mul3([1, 0, 0, 0, cp, -sp, 0, sp, cp], [cy, 0, -sy, 0, 1, 0, sy, 0, cy]));
    return new Float32Array([m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]]);   // column-major for WebGL
  }

  var tx = 0, ty = 0, mx = 0, my = 0, sc = 0, scTarget = 0;
  if (P) {
    try {
      P.addEventListener('mousemove', function (e) { tx = e.clientX / P.innerWidth * 2 - 1; ty = e.clientY / P.innerHeight * 2 - 1; }, { passive: true });
      var scroller = P.document.querySelector('[data-testid="stMain"]') || P.document.querySelector('section.main');
      if (scroller) scroller.addEventListener('scroll', function () { scTarget = scroller.scrollTop / 900; }, { passive: true });
    } catch (e) {}
  }
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  var W = 0, H = 0, dpr = 1;
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 1.5);
    var w = Math.max(window.innerWidth, 2), h = Math.max(window.innerHeight, 2);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) { canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr); }
    W = canvas.width; H = canvas.height; gl.viewport(0, 0, W, H);
  }

  gl.enable(gl.BLEND); gl.clearColor(0, 0, 0, 0);
  var t0 = performance.now();
  function frame(now) {
    resize();
    var t = reduce ? 40 : (now - t0) / 1000;
    mx += (tx - mx) * 0.05; my += (ty - my) * 0.05; sc += (scTarget - sc) * 0.08;
    var rot = rotMat(t * 0.004 + mx * 0.05, my * 0.03 + Math.sin(t * 0.02) * 0.02 - sc * 0.05, t * 0.0015);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.blendFunc(gl.ONE, gl.ONE);                                         // stars add their light together
    drawStars(farBuf, 0, rot, t, W / H, dpr);
    drawStars(nearBuf, 1, rot, t, W / H, dpr);
    gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);                         // planets cover the stars behind them
    for (var i = 0; i < PLANETS.length; i++) drawPlanet(PLANETS[i], t, W, H, mx, my, sc);
    if (!reduce) requestAnimationFrame(frame);
  }
  window.addEventListener('resize', function () { if (reduce) requestAnimationFrame(frame); });
  canvas.addEventListener('webglcontextlost', function (e) { e.preventDefault(); });
  canvas.addEventListener('webglcontextrestored', function () { location.reload(); });
  requestAnimationFrame(frame);
})();
</script>
</body></html>"""


def render_space_3d() -> None:
    """Put the 3D space behind the page. Call once, before your tabs."""
    components.html(SPACE_3D_HTML, height=0)
