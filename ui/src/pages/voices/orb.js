// The voice orb (WebGL).
// An animated voice orb that reacts to what is playing.
//
// Ported from the ElevenLabs UI `Orb` component (React + three.js) to plain
// WebGL2 so the app keeps its no-build, no-dependency frontend. The fragment
// shader is theirs, nearly verbatim; the scene around it is rewritten.
//
//   MIT License — Copyright (c) 2025 Eleven Labs Inc.
//   https://github.com/elevenlabs/ui (apps/www/registry/elevenlabs-ui/ui/orb.tsx)
//
// Usage:
//   const orb = createOrb(canvas, { colors: ['#CADCFC', '#A0B9D1'], seed: 7 });
//   orb.follow(audioElement);   // volume comes from the audio that is playing
//   orb.destroy();

const VERTEX = `#version 300 es
in vec2 aPosition;
out vec2 vUv;
void main() {
  vUv = aPosition * 0.5 + 0.5;
  gl_Position = vec4(aPosition, 0.0, 1.0);
}`;

const FRAGMENT = `#version 300 es
precision highp float;
uniform float uTime;
uniform float uAnimation;
uniform float uInverted;
uniform float uOffsets[7];
uniform vec3 uColor1;
uniform vec3 uColor2;
uniform float uInputVolume;
uniform float uOutputVolume;
uniform float uOpacity;
uniform sampler2D uPerlinTexture;
in vec2 vUv;
out vec4 fragColor;

const float PI = 3.14159265358979323846;

bool drawOval(vec2 polarUv, vec2 polarCenter, float a, float b, bool reverseGradient, float softness, out vec4 color) {
  vec2 p = polarUv - polarCenter;
  float oval = (p.x * p.x) / (a * a) + (p.y * p.y) / (b * b);
  float edge = smoothstep(1.0, 1.0 - softness, oval);
  if (edge > 0.0) {
    float gradient = reverseGradient ? (1.0 - (p.x / a + 1.0) / 2.0) : ((p.x / a + 1.0) / 2.0);
    gradient = mix(0.5, gradient, 0.1);
    color = vec4(vec3(gradient), 0.85 * edge);
    return true;
  }
  return false;
}

vec3 colorRamp(float grayscale, vec3 color1, vec3 color2, vec3 color3, vec3 color4) {
  if (grayscale < 0.33) return mix(color1, color2, grayscale * 3.0);
  if (grayscale < 0.66) return mix(color2, color3, (grayscale - 0.33) * 3.0);
  return mix(color3, color4, (grayscale - 0.66) * 3.0);
}

vec2 hash2(vec2 p) {
  return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453);
}

float noise2D(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float n = mix(
    mix(dot(hash2(i + vec2(0.0, 0.0)), f - vec2(0.0, 0.0)),
        dot(hash2(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
    mix(dot(hash2(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)),
        dot(hash2(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x),
    u.y);
  return 0.5 + 0.5 * n;
}

float sharpRing(vec3 decomposed, float time) {
  float noise = mix(noise2D(vec2(decomposed.x, time) * 5.0),
                    noise2D(vec2(decomposed.y, time) * 5.0), decomposed.z);
  noise = (noise - 0.5) * 2.5;
  return 1.0 + noise * 0.3 * 1.5;
}

float smoothRing(vec3 decomposed, float time) {
  float noise = mix(noise2D(vec2(decomposed.x, time) * 6.0),
                    noise2D(vec2(decomposed.y, time) * 6.0), decomposed.z);
  noise = (noise - 0.5) * 5.0;
  return 0.9 + noise * 0.2;
}

float flow(vec3 decomposed, float time) {
  return mix(texture(uPerlinTexture, vec2(time, decomposed.x / 2.0)).r,
             texture(uPerlinTexture, vec2(time, decomposed.y / 2.0)).r, decomposed.z);
}

void main() {
  vec2 uv = vUv * 2.0 - 1.0;
  float radius = length(uv);
  if (radius > 1.0) { fragColor = vec4(0.0); return; }   // the circle the mesh used to be
  float theta = atan(uv.y, uv.x);
  if (theta < 0.0) theta += 2.0 * PI;
  vec3 decomposed = vec3(theta / (2.0 * PI),
                         mod(theta / (2.0 * PI) + 0.5, 1.0) + 1.0,
                         abs(theta / PI - 1.0));
  float noise = flow(decomposed, radius * 0.03 - uAnimation * 0.2) - 0.5;
  theta += noise * mix(0.08, 0.25, uOutputVolume);

  vec4 color = vec4(1.0);
  float originalCenters[7] = float[7](0.0, 0.5 * PI, 1.0 * PI, 1.5 * PI, 2.0 * PI, 2.5 * PI, 3.0 * PI);
  float centers[7];
  for (int i = 0; i < 7; i++) centers[i] = originalCenters[i] + 0.5 * sin(uTime / 20.0 + uOffsets[i]);

  vec4 ovalColor;
  for (int i = 0; i < 7; i++) {
    float n = texture(uPerlinTexture, vec2(mod(centers[i] + uTime * 0.05, 1.0), 0.5)).r;
    float a = 0.5 + n * 0.3;
    float b = n * mix(3.5, 2.5, uInputVolume);
    bool reverseGradient = (i % 2 == 1);
    float distTheta = min(abs(theta - centers[i]),
                          min(abs(theta + 2.0 * PI - centers[i]), abs(theta - 2.0 * PI - centers[i])));
    if (drawOval(vec2(distTheta, radius), vec2(0.0), a, b, reverseGradient, 0.6, ovalColor)) {
      color.rgb = mix(color.rgb, ovalColor.rgb, ovalColor.a);
      color.a = max(color.a, ovalColor.a);
    }
  }

  float ringRadius1 = sharpRing(decomposed, uTime * 0.1);
  float ringRadius2 = smoothRing(decomposed, uTime * 0.1);
  float inputRadius1 = radius + uInputVolume * 0.2;
  float inputRadius2 = radius + uInputVolume * 0.15;
  float opacity1 = mix(0.2, 0.6, uInputVolume);
  float opacity2 = mix(0.15, 0.45, uInputVolume);
  float ringAlpha1 = (inputRadius2 >= ringRadius1) ? opacity1 : 0.0;
  float ringAlpha2 = smoothstep(ringRadius2 - 0.05, ringRadius2 + 0.05, inputRadius1) * opacity2;
  float totalRingAlpha = max(ringAlpha1, ringAlpha2);
  color.rgb = 1.0 - (1.0 - color.rgb) * (1.0 - vec3(1.0) * totalRingAlpha);

  float luminance = mix(color.r, 1.0 - color.r, uInverted);
  color.rgb = colorRamp(luminance, vec3(0.0), uColor1, uColor2, vec3(1.0));
  color.a *= uOpacity;
  // Soften the outer edge the circle geometry used to give for free.
  color.a *= smoothstep(1.0, 0.985, radius);
  fragColor = vec4(color.rgb * color.a, color.a);
}`;

const NOISE_URL = '/orb-noise.png';

function splitmix32(a) {
  return () => {
    a |= 0; a = (a + 0x9e3779b9) | 0;
    let t = a ^ (a >>> 16); t = Math.imul(t, 0x21f0aaad);
    t ^= t >>> 15; t = Math.imul(t, 0x735a2d97);
    return ((t ^= t >>> 15) >>> 0) / 4294967296;
  };
}

const clamp01 = n => (Number.isFinite(n) ? Math.min(1, Math.max(0, n)) : 0);

function hexRgb(hex) {
  const v = parseInt(String(hex).replace('#', ''), 16);
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255];
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    throw new Error(gl.getShaderInfoLog(shader) || 'orb shader failed to compile');
  }
  return shader;
}

// A shared analyser per <audio>, so several orbs (or re-renders) can follow
// the same element; an element can only be wired into Web Audio once.
const analysers = new WeakMap();
let audioContext = null;

// Call from the click that leads to playback, before any await: a context
// created later (after a generation that took seconds) is no longer allowed to
// start, and an <audio> wired into a suspended context plays silence.
export function primeAudio() {
  audioContext = audioContext || new AudioContext();
  if (audioContext.state === 'suspended') audioContext.resume().catch(() => {});
  return audioContext;
}

function analyserFor(audio) {
  if (analysers.has(audio)) return analysers.get(audio);
  primeAudio();
  const source = audioContext.createMediaElementSource(audio);
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  analyser.connect(audioContext.destination);
  const entry = { analyser, buffer: new Float32Array(analyser.fftSize) };
  analysers.set(audio, entry);
  return entry;
}

export function createOrb(canvas, { colors = ['#CADCFC', '#A0B9D1'], seed } = {}) {
  const gl = canvas.getContext('webgl2', { alpha: true, antialias: true, premultipliedAlpha: true });
  if (!gl) {
    canvas.classList.add('orb-unsupported');
    return { follow() {}, setColors() {}, destroy() {} };
  }
  const program = gl.createProgram();
  gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERTEX));
  gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAGMENT));
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    throw new Error(gl.getProgramInfoLog(program) || 'orb program failed to link');
  }
  gl.useProgram(program);
  const quad = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, quad);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const position = gl.getAttribLocation(program, 'aPosition');
  gl.enableVertexAttribArray(position);
  gl.vertexAttribPointer(position, 2, gl.FLOAT, false, 0, 0);
  gl.enable(gl.BLEND);
  gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);

  const u = name => gl.getUniformLocation(program, name);
  const loc = {
    time: u('uTime'), animation: u('uAnimation'), inverted: u('uInverted'), offsets: u('uOffsets'),
    color1: u('uColor1'), color2: u('uColor2'), input: u('uInputVolume'), output: u('uOutputVolume'),
    opacity: u('uOpacity'), noise: u('uPerlinTexture'),
  };
  const random = splitmix32(seed ?? Math.floor(Math.random() * 2 ** 32));
  gl.uniform1fv(loc.offsets, Float32Array.from({ length: 7 }, () => random() * Math.PI * 2));

  const texture = gl.createTexture();
  gl.bindTexture(gl.TEXTURE_2D, texture);
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array([128, 128, 128, 255]));
  for (const [k, v] of [[gl.TEXTURE_WRAP_S, gl.REPEAT], [gl.TEXTURE_WRAP_T, gl.REPEAT],
    [gl.TEXTURE_MIN_FILTER, gl.LINEAR], [gl.TEXTURE_MAG_FILTER, gl.LINEAR]]) gl.texParameteri(gl.TEXTURE_2D, k, v);
  const image = new Image();
  image.onload = () => {
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
  };
  image.src = NOISE_URL;
  gl.uniform1i(loc.noise, 0);

  let target1 = hexRgb(colors[0]), target2 = hexRgb(colors[1]);
  const color1 = [...target1], color2 = [...target2];
  let time = 0, animation = 0.1, speed = 0.1, opacity = 0, curIn = 0, curOut = 0;
  let following = null, frame = 0, last = performance.now();

  const volume = () => {
    // No audio, or paused: the idle breathing of the original's null state.
    if (!following || following.audio.paused) return [0, 0.3];
    const { analyser, buffer } = following.entry;
    analyser.getFloatTimeDomainData(buffer);
    let sum = 0;
    for (const v of buffer) sum += v * v;
    const level = clamp01(Math.sqrt(sum / buffer.length) * 4.5);
    return [clamp01(0.35 + level * 0.9), clamp01(0.45 + level)];
  };

  const resize = () => {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.round(canvas.clientWidth * ratio), h = Math.round(canvas.clientHeight * ratio);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    gl.viewport(0, 0, canvas.width, canvas.height);
  };

  const draw = now => {
    const delta = Math.min(0.1, (now - last) / 1000);
    last = now;
    resize();
    time += delta * 0.5;
    opacity = Math.min(1, opacity + delta * 2);
    const [targetIn, targetOut] = volume();
    curIn += (targetIn - curIn) * 0.2;
    curOut += (targetOut - curOut) * 0.2;
    speed += (0.1 + (1 - (curOut - 1) ** 2) * 0.9 - speed) * 0.12;
    animation += delta * speed;
    for (let i = 0; i < 3; i++) {
      color1[i] += (target1[i] - color1[i]) * 0.08;
      color2[i] += (target2[i] - color2[i]) * 0.08;
    }
    // Doblarr sets its theme on the .app shell; the original read <html>.
    const shell = canvas.closest('.app') || document.documentElement;
    const dark = shell.dataset.theme === 'dark' || shell.classList.contains('dark');
    gl.uniform1f(loc.time, time);
    gl.uniform1f(loc.animation, animation);
    gl.uniform1f(loc.inverted, dark ? 1 : 0);
    gl.uniform3fv(loc.color1, color1);
    gl.uniform3fv(loc.color2, color2);
    gl.uniform1f(loc.input, curIn);
    gl.uniform1f(loc.output, curOut);
    gl.uniform1f(loc.opacity, opacity);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    frame = requestAnimationFrame(draw);
  };
  frame = requestAnimationFrame(draw);

  return {
    // Drive the orb from an <audio> element's actual level while it plays.
    follow(audio) {
      if (!audio) { following = null; return; }
      following = { audio, entry: analyserFor(audio) };
      audioContext?.resume?.();
    },
    setColors(a, b) { target1 = hexRgb(a); target2 = hexRgb(b); },
    destroy() {
      cancelAnimationFrame(frame);
      gl.getExtension('WEBGL_lose_context')?.loseContext();
    },
  };
}
