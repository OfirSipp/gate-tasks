// "Earl Grey" -- a realistic British Shorthair skin for the desktop pet.
// Unlike the pixel skins it is painted with smooth canvas shapes (shaded blue-grey coat,
// fur texture, copper eyes, round cheeks) but runs on the exact same physics/behaviour core.
// Written for Gate Tasks; plugs into pet-core.js's SKINS table and pet-dom.js's paintPet.

import { Mood, PIXEL, SKINS, Skin } from "./pet-core.js";

const COLUMNS = 22; // 88 px wide hit box
const BODY_ROWS = 13; // (13 + 2) * 4 = 60 px tall hit box
const blank = (n) => Array.from({ length: n }, () => ".".repeat(COLUMNS));
const LEGS = Object.fromEntries(["stand", "walk_a", "walk_b", "tuck", "dangle"].map((k) => [k, blank(2)]));

const COAT = { hi: "#B4BCC6", light: "#9BA4AF", mid: "#808A96", dark: "#5F6873", deep: "#474E58" };
const PAD = "#C3CAD2";
const NOSE = "#5E5560";
const INNER_EAR = "#9C8A90";
const IRIS_IN = "#F7BF45";
const IRIS_OUT = "#C46A17";
const LINE = "#30353C";

// Fixed, seeded fur strokes so the texture doesn't shimmer.
let seed = 11;
const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
const FUR = Array.from({ length: 90 }, () => {
  const a = rnd() * Math.PI * 2;
  const d = Math.sqrt(rnd());
  return { x: Math.cos(a) * d, y: Math.sin(a) * d, len: 2 + rnd() * 3, tilt: (rnd() - 0.5) * 0.8, tone: rnd() };
});

function ellipse(ctx, x, y, rx, ry, rot = 0) {
  ctx.beginPath();
  ctx.ellipse(x, y, rx, ry, rot, 0, Math.PI * 2);
}

function coatGradient(ctx, top, bottom) {
  const g = ctx.createLinearGradient(0, top, 0, bottom);
  g.addColorStop(0, COAT.hi);
  g.addColorStop(0.35, COAT.light);
  g.addColorStop(0.75, COAT.mid);
  g.addColorStop(1, COAT.dark);
  return g;
}

function fur(ctx, cx, cy, rx, ry) {
  ctx.save();
  ellipse(ctx, cx, cy, rx, ry);
  ctx.clip();
  ctx.lineCap = "round";
  ctx.lineWidth = 0.9;
  for (const f of FUR) {
    const x = cx + f.x * rx;
    const y = cy + f.y * ry;
    ctx.strokeStyle = f.tone > 0.55 ? "rgba(214,221,229,0.16)" : "rgba(52,58,66,0.13)";
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x - f.len * Math.cos(f.tilt) * 0.6, y + f.len * Math.sin(f.tilt) + f.len * 0.5);
    ctx.stroke();
  }
  ctx.restore();
}

function pose(pet) {
  const mood = pet.mood;
  const emo = pet.expression;
  const t = pet.clock || 0;
  const p = {
    by: -28, legLen: 12, legMode: "stand", tail: "up", sleep: false, shadow: true,
    breathe: Math.sin(t * 2.2) * 0.6, raise: false, puff: emo === "angry" ? 1.06 : 1.0,
  };
  if (mood === Mood.SLEEP) Object.assign(p, { sleep: true, by: -15, tail: "wrap", legMode: "none" });
  else if (mood === Mood.CROUCH) Object.assign(p, { by: -22, legLen: 6, tail: pet.pouncing ? "low-twitch" : "up" });
  else if (mood === Mood.LAND) Object.assign(p, { by: -24, legLen: 8 });
  else if (mood === Mood.WALK) p.legMode = "walk";
  else if (mood === Mood.AIR) Object.assign(p, { legMode: pet.vy < 0 ? "tuck" : "dangle", shadow: false, tail: "stream" });
  else if (mood === Mood.HELD || mood === Mood.RIDE) {
    Object.assign(p, { legMode: "hang", shadow: mood === Mood.RIDE, tail: "hang", by: -30 });
  }
  if (pet.armsRaised && ![Mood.HELD, Mood.RIDE, Mood.AIR].includes(mood)) p.raise = true;
  if (emo === "happy" || p.raise) p.tail = "high";
  if (emo === "sad") p.tail = "low";
  if (emo === "angry") p.tail = "bush";
  return p;
}

function tailPath(p, t) {
  const by = p.by;
  const sway = Math.sin(t * 3) * 2.5;
  switch (p.tail) {
    case "wrap": return [[-30, -10], [-46, 2], [8, -2]];
    case "hang": return [[-32, by + 4], [-40, by + 14], [-36 + sway, by + 28]];
    case "stream": return [[-32, by - 2], [-46, by - 4], [-54, by - 10 + sway]];
    case "high": return [[-32, by - 4], [-40, by - 10], [-38 + sway, by - 34]];
    case "low": return [[-32, by + 2], [-46, by + 6], [-50, -3]];
    case "low-twitch": return [[-32, by], [-46, by + 2], [-54, by - 4 + Math.sin(t * 14) * 4]];
    case "bush": return [[-32, by - 2], [-52, by - 2], [-48, by - 28]];
    default: return [[-32, by - 2], [-50, by - 2], [-46 + sway * 0.6, by - 24]];
  }
}

function drawTail(ctx, p, t) {
  const [[sx, sy], [cx, cy], [ex, ey]] = tailPath(p, t);
  const w = p.tail === "bush" ? 13 : 9;
  ctx.lineCap = "round";
  for (const [lw, colour] of [[w + 1.6, COAT.deep], [w, COAT.mid], [w * 0.45, COAT.light]]) {
    ctx.strokeStyle = colour;
    ctx.lineWidth = lw;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.quadraticCurveTo(cx, cy, ex, ey);
    ctx.stroke();
  }
}

function legGeometry(p, pet) {
  // [x at shoulder/hip, near?] -- far legs are drawn behind the body, darker.
  const legs = [
    { x: -20, near: false, front: false }, { x: 12, near: false, front: true },
    { x: -14, near: true, front: false }, { x: 18, near: true, front: true },
  ];
  const ph = (pet.walkPhase || 0) * Math.PI;
  const t = pet.clock || 0;
  return legs.map((leg) => {
    const top = p.by + 10;
    let dx = 0;
    let len = p.legLen + 6;
    let lift = 0;
    if (p.legMode === "walk") {
      const group = leg.near === leg.front ? 1 : -1;
      const s = Math.sin(ph) * group;
      dx = s * 5;
      lift = Math.max(0, Math.cos(ph) * group) * 3;
    } else if (p.legMode === "tuck") {
      dx = leg.front ? 7 : -7;
      len -= 5;
    } else if (p.legMode === "dangle") {
      dx = leg.front ? 4 : -4;
      len += 3;
    } else if (p.legMode === "hang") {
      dx = Math.sin(t * 5 + leg.x) * 2;
      len += 7;
    }
    let bottom = top + len - lift;
    if (p.legMode === "stand" || p.legMode === "walk") bottom = Math.min(bottom, -lift);
    const raised = p.raise && leg.near && leg.front;
    return { ...leg, top, footX: raised ? leg.x + 22 : leg.x + dx, footY: raised ? p.by + 2 : bottom, raised };
  });
}

function drawLeg(ctx, leg) {
  const w = leg.near ? 10 : 9;
  ctx.lineCap = "round";
  ctx.strokeStyle = leg.near ? COAT.mid : COAT.dark;
  ctx.lineWidth = w;
  ctx.beginPath();
  ctx.moveTo(leg.x, leg.top);
  ctx.lineTo(leg.footX, leg.footY - 2);
  ctx.stroke();
  if (leg.near) {
    ctx.strokeStyle = "rgba(190,198,207,0.35)";
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(leg.x + 2, leg.top + 2);
    ctx.lineTo(leg.footX + 2, leg.footY - 3);
    ctx.stroke();
  }
  ellipse(ctx, leg.footX + 1.2, leg.footY - 2, w * 0.68, 3.2);
  ctx.fillStyle = leg.near ? COAT.light : COAT.mid;
  ctx.fill();
}

function drawEar(ctx, base1, tip, base2) {
  ctx.beginPath();
  ctx.moveTo(...base1);
  ctx.quadraticCurveTo(tip[0], tip[1] - 1, ...tip);
  ctx.quadraticCurveTo(tip[0] + 0.5, tip[1] + 1, ...base2);
  ctx.closePath();
  ctx.fillStyle = COAT.mid;
  ctx.fill();
  ctx.strokeStyle = COAT.deep;
  ctx.lineWidth = 0.8;
  ctx.stroke();
  const ix = (base1[0] + base2[0] + tip[0]) / 3;
  const iy = (base1[1] + base2[1] + tip[1]) / 3;
  ctx.beginPath();
  ctx.moveTo(base1[0] * 0.7 + ix * 0.3, base1[1] * 0.7 + iy * 0.3);
  ctx.lineTo(tip[0] * 0.6 + ix * 0.4, tip[1] * 0.6 + iy * 0.4);
  ctx.lineTo(base2[0] * 0.7 + ix * 0.3, base2[1] * 0.7 + iy * 0.3);
  ctx.closePath();
  ctx.fillStyle = INNER_EAR;
  ctx.fill();
}

function drawEye(ctx, x, y, r, pet, lookX, lookY) {
  const emo = pet.expression;
  if (pet.eyesClosed || emo === "happy") {
    ctx.strokeStyle = LINE;
    ctx.lineWidth = 1.5;
    ctx.lineCap = "round";
    ctx.beginPath();
    if (emo === "happy" && !pet.eyesClosed) ctx.arc(x, y + 1.5, r * 0.8, Math.PI * 1.15, Math.PI * 1.85);
    else ctx.arc(x, y - 1, r * 0.85, Math.PI * 0.15, Math.PI * 0.85);
    ctx.stroke();
    return;
  }
  ellipse(ctx, x, y, r + 0.9, r + 0.7);
  ctx.fillStyle = LINE;
  ctx.fill();
  const g = ctx.createRadialGradient(x - r * 0.2, y - r * 0.2, 0.5, x, y, r);
  g.addColorStop(0, IRIS_IN);
  g.addColorStop(1, IRIS_OUT);
  ellipse(ctx, x, y, r, r);
  ctx.fillStyle = g;
  ctx.fill();
  const slit = emo === "angry" ? 0.7 : 1.7;
  ellipse(ctx, x + lookX * r * 0.35, y + lookY * r * 0.25, slit, r * 0.8);
  ctx.fillStyle = "#0E0E10";
  ctx.fill();
  ellipse(ctx, x - r * 0.35 + lookX * 0.6, y - r * 0.4, r * 0.24, r * 0.24);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.fill();
  // eyelids for moods
  if (emo === "sad" || emo === "angry") {
    ctx.save();
    ellipse(ctx, x, y, r + 1, r + 1);
    ctx.clip();
    ctx.fillStyle = COAT.light;
    ctx.beginPath();
    if (emo === "sad") ctx.rect(x - r - 2, y - r - 2, 2 * r + 4, r * 0.9);
    else {
      ctx.moveTo(x - r - 2, y - r * 0.9);
      ctx.lineTo(x + r + 2, y - r * 0.1);
      ctx.lineTo(x + r + 2, y - r - 3);
      ctx.lineTo(x - r - 2, y - r - 3);
    }
    ctx.fill();
    ctx.restore();
  }
}

function drawHead(ctx, hx, hy, pet, p, facing) {
  const emo = pet.expression;
  // ears (tips move with mood)
  let farTip = [hx - 15, hy - 20];
  let nearTip = [hx + 15, hy - 20];
  if (emo === "angry") { farTip = [hx - 22, hy - 11]; nearTip = [hx + 7, hy - 18]; }
  else if (emo === "sad" || p.sleep) { farTip = [hx - 21, hy - 13]; nearTip = [hx + 22, hy - 12]; }
  drawEar(ctx, [hx - 17, hy - 6], farTip, [hx - 5, hy - 15]);
  drawEar(ctx, [hx + 5, hy - 15], nearTip, [hx + 18, hy - 5]);

  // big round head + chubby jowls
  ctx.fillStyle = coatGradient(ctx, hy - 16, hy + 14);
  ellipse(ctx, hx, hy - 1, 18.5, 16);
  ctx.fill();
  ellipse(ctx, hx + 0.5, hy + 5, 20, 10.5);
  ctx.fill();
  fur(ctx, hx, hy, 18, 15);
  ctx.strokeStyle = "rgba(225,232,240,0.22)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.ellipse(hx, hy - 1, 18, 15.5, 0, Math.PI * 1.1, Math.PI * 1.9);
  ctx.stroke();

  // eyes (look toward the cursor; mirrored frame)
  const lookX = (pet.look ? pet.look() : 0) * facing;
  const lookY = pet.cursor && pet.cursor[1] < pet.y - 80 ? -1 : 0;
  drawEye(ctx, hx - 6, hy - 2, 4.6, pet, lookX, lookY);
  drawEye(ctx, hx + 6.5, hy - 2, 4.6, pet, lookX, lookY);

  // muzzle, nose, mouth
  ctx.fillStyle = PAD;
  ellipse(ctx, hx - 2.4, hy + 7, 4, 3);
  ctx.fill();
  ellipse(ctx, hx + 3.2, hy + 7, 4, 3);
  ctx.fill();
  ctx.fillStyle = NOSE;
  ctx.beginPath();
  ctx.moveTo(hx - 2.2, hy + 3.2);
  ctx.lineTo(hx + 3.0, hy + 3.2);
  ctx.lineTo(hx + 0.4, hy + 6.0);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = LINE;
  ctx.lineWidth = 0.9;
  ctx.beginPath();
  ctx.moveTo(hx + 0.4, hy + 6);
  ctx.lineTo(hx + 0.4, hy + 7.6);
  if (emo === "sad") {
    ctx.moveTo(hx - 2.6, hy + 9.8);
    ctx.quadraticCurveTo(hx + 0.4, hy + 7.6, hx + 3.4, hy + 9.8);
  } else {
    ctx.quadraticCurveTo(hx - 1.4, hy + 9.4, hx - 3, hy + 8.2);
    ctx.moveTo(hx + 0.4, hy + 7.6);
    ctx.quadraticCurveTo(hx + 2.2, hy + 9.4, hx + 3.8, hy + 8.2);
  }
  ctx.stroke();
  if (emo === "angry") {
    ellipse(ctx, hx + 0.4, hy + 10.5, 2.4, 1.6);
    ctx.fillStyle = "#7A2E34";
    ctx.fill();
  }
  // whiskers
  ctx.strokeStyle = "rgba(236,240,245,0.6)";
  ctx.lineWidth = 0.6;
  for (const [sx, dir] of [[hx - 5, -1], [hx + 6, 1]]) {
    for (const k of [-1, 0, 1]) {
      ctx.beginPath();
      ctx.moveTo(sx, hy + 7 + k);
      ctx.quadraticCurveTo(sx + dir * 8, hy + 6 + k * 2, sx + dir * 16, hy + 6 + k * 3.5);
      ctx.stroke();
    }
  }
}

function paint(ctx, pet, { width = 120, feet = 124, dark = true } = {}) {
  const p = pose(pet);
  const t = pet.clock || 0;
  const facing = pet.facing < 0 ? -1 : 1;
  BRITISH_SHORTHAIR._facing = facing;
  ctx.save();
  ctx.translate(width / 2, feet);
  ctx.scale(1 + pet.squash, 1 - pet.squash);
  if (p.shadow) {
    ellipse(ctx, 0, 0, 34, 3.5);
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fill();
  }
  ctx.scale(facing, 1);
  const by = p.by + p.breathe;
  const pp = { ...p, by };

  if (p.sleep) {
    drawTail(ctx, pp, t);
    ctx.fillStyle = coatGradient(ctx, by - 14, 0);
    ellipse(ctx, -3, by + 1, 31, 14);
    ctx.fill();
    fur(ctx, -3, by + 1, 31, 14);
    // tucked front paws
    ctx.fillStyle = COAT.light;
    ellipse(ctx, 20, -3.5, 6, 3.2);
    ctx.fill();
    ellipse(ctx, 28, -3, 5.5, 3);
    ctx.fill();
    drawTail(ctx, { ...pp, tail: "wrap" }, t);
    drawHead(ctx, 21, -21 + p.breathe * 0.5, pet, p, facing);
    ctx.restore();
    return;
  }

  const legs = legGeometry(pp, pet);
  drawTail(ctx, pp, t);
  legs.filter((l) => !l.near).forEach((l) => drawLeg(ctx, l));

  ctx.save();
  ctx.scale(p.puff, p.puff);
  ctx.fillStyle = coatGradient(ctx, by - 17, by + 17);
  ellipse(ctx, -4, by, 31, 16.5);
  ctx.fill();
  ellipse(ctx, 13, by + 1, 14, 16); // chest
  ctx.fill();
  fur(ctx, -4, by, 31, 16.5);
  ctx.strokeStyle = dark ? "rgba(225,232,240,0.22)" : "rgba(255,255,255,0.3)";
  ctx.lineWidth = 1.2;
  ctx.beginPath();
  ctx.ellipse(-4, by, 30.5, 16, 0, Math.PI * 1.08, Math.PI * 1.92);
  ctx.stroke();
  ctx.restore();

  legs.filter((l) => l.near && !l.raised).forEach((l) => drawLeg(ctx, l));
  drawHead(ctx, 23, by - 13, pet, p, facing);
  legs.filter((l) => l.raised).forEach((l) => drawLeg(ctx, l));
  ctx.restore();
}

export const BRITISH_SHORTHAIR = new Skin({
  key: "bsh", name: "Earl Grey (British Shorthair)",
  body: blank(BODY_ROWS), armsUp: blank(BODY_ROWS), sadBody: blank(BODY_ROWS), legs: LEGS,
  face: () => {}, palette: {}, angry: {}, stalks: true, outline: false, paint,
});
BRITISH_SHORTHAIR._facing = 1;
// Tear drops come from the eyes, which swap sides when the cat turns around.
Object.defineProperty(BRITISH_SHORTHAIR, "tears", {
  get() {
    const cols = [23 - 6, 23 + 6.5].map((x) => (this._facing * x) / PIXEL + COLUMNS / 2 - 0.5);
    return cols.map((c) => [4.3, c]);
  },
});

SKINS.bsh = BRITISH_SHORTHAIR;
