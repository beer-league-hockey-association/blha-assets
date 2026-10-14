// A strict stand-in for EffectCraft's scripting object model, for testing the BLHA Video Kit
// scripts without the app. It implements only the calls the kit uses, with the signatures the
// EffectCraft prelude defines, and throws on anything else (an unknown match name, a missing
// method), so a typo fails here instead of in front of the Commissioner.
//
// usage: node video_kit_jsx_mock.js <script.jsx> <metrics.json> <out.json>
// Writes every composition the script built (layers, timing, keyframes, text) as JSON for
// tools/video_kit_preview.py to draw.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [scriptPath, metricsPath, outPath] = process.argv.slice(2);
const METRICS = JSON.parse(fs.readFileSync(metricsPath, "utf8"));
const out = { comps: [], alerts: [], log: [], imports: [] };

function fail(msg) { throw new Error("[mock] " + msg); }

// ------------------------------------------------------------------ files
class File {
  constructor(p) { this.__path = String(p); }
  get fsName() { return path.resolve(this.__path); }
  get name() { return path.basename(this.__path); }
  get parent() { return new Folder(path.dirname(path.resolve(this.__path))); }
  // EffectCraft's default file gate: with no saved project, scripts can't see any file.
  get exists() { return false; }
  toString() { return this.__path; }
}
class Folder {
  constructor(p) { this.__path = String(p); }
  get fsName() { return path.resolve(this.__path); }
  get name() { return path.basename(this.__path); }
  get exists() { return fs.existsSync(this.__path) && fs.statSync(this.__path).isDirectory(); }
}

function pngSize(p) {
  const b = fs.readFileSync(p);
  if (b.toString("ascii", 1, 4) !== "PNG") fail("not a PNG: " + p);
  return [b.readUInt32BE(16), b.readUInt32BE(20)];
}
function wavSeconds(p) {
  const b = fs.readFileSync(p);
  const rate = b.readUInt32LE(24), bytesPerSec = b.readUInt32LE(28);
  let i = 12;
  while (i < b.length - 8) {
    const id = b.toString("ascii", i, i + 4), size = b.readUInt32LE(i + 4);
    if (id === "data") return size / bytesPerSec;
    i += 8 + size + (size & 1);
  }
  return 0;
}

// ------------------------------------------------------------------ enums
function enumOf(names, base) { const e = {}; names.forEach((n, i) => { e[n] = base + i; }); return e; }
const KeyframeInterpolationType = enumOf(["LINEAR", "BEZIER", "HOLD"], 6612);
const ParagraphJustification = enumOf(["LEFT_JUSTIFY", "CENTER_JUSTIFY", "RIGHT_JUSTIFY"], 7413);
const ImportAsType = enumOf(["COMP_CROPPED_LAYERS", "FOOTAGE", "COMP", "PROJECT"], 3812);

// ------------------------------------------------------------------ text
const FONT_NAMES = Object.keys(METRICS);
class TextDocument {
  constructor(text) {
    this.text = text === undefined ? "" : String(text);
    this.font = "ArialMT"; this.fontSize = 72; this.fillColor = [1, 1, 1]; this.applyFill = true;
    this.applyStroke = false; this.strokeColor = [0, 0, 0]; this.strokeWidth = 0; this.tracking = 0;
    this.justification = ParagraphJustification.LEFT_JUSTIFY; this.autoLeading = true; this.leading = 86.4;
  }
  clone() { const d = new TextDocument(this.text); Object.assign(d, JSON.parse(JSON.stringify(this))); return d; }
}
function checkDoc(d) {
  if (!(d instanceof TextDocument)) fail("Source Text needs a TextDocument");
  if (!FONT_NAMES.includes(d.font)) fail("unknown font " + d.font);
  if (!(d.fontSize > 0)) fail("bad fontSize " + d.fontSize);
  if (!Object.values(ParagraphJustification).includes(d.justification)) fail("bad justification " + d.justification);
  ["fillColor"].forEach(k => { const c = d[k]; if (!Array.isArray(c) || c.length < 3 || c.some(v => !(v >= 0 && v <= 1))) fail("bad " + k + " " + JSON.stringify(c)); });
}
function textRect(d) {
  const m = METRICS[d.font];
  const s = d.fontSize / m.upm;
  const lines = String(d.text).split(/\r\n|\r|\n/);
  let w = 0;
  for (const ln of lines) {
    let a = 0;
    for (const ch of ln) a += (m.adv[ch] !== undefined ? m.adv[ch] : m.default);
    w = Math.max(w, a * s + d.tracking / 1000 * d.fontSize * Math.max(0, ln.length - 1));
  }
  const cap = m.cap * s;
  const lead = d.autoLeading ? d.fontSize * 1.2 : d.leading;
  const h = cap + (lines.length - 1) * lead;
  const left = d.justification === ParagraphJustification.CENTER_JUSTIFY ? -w / 2 :
    d.justification === ParagraphJustification.RIGHT_JUSTIFY ? -w : 0;
  return { left, top: -cap, width: w, height: h };
}

// ------------------------------------------------------------------ properties
const DIMS = { "ADBE Position": 2, "ADBE Scale": 2, "ADBE Anchor Point": 2, "ADBE Opacity": 1,
  "ADBE Vector Rect Size": 2, "ADBE Vector Fill Color": 4, "ADBE Text Document": "text" };

class Property {
  constructor(layer, matchName, value) {
    this.__layer = layer; this.matchName = matchName; this.name = matchName;
    this.__value = value; this.__keys = []; this.__expr = "";
  }
  __check(v) {
    const d = DIMS[this.matchName];
    if (d === "text") return checkDoc(v), v.clone();
    if (d === 1) { if (typeof v !== "number" || !isFinite(v)) fail(this.matchName + " needs a number, got " + JSON.stringify(v)); return v; }
    if (!Array.isArray(v) || v.some(x => typeof x !== "number" || !isFinite(x))) fail(this.matchName + " needs numbers, got " + JSON.stringify(v));
    if (d === 4) { if (v.length < 3 || v.length > 4 || v.some(x => x < 0 || x > 1)) fail("bad color " + JSON.stringify(v)); return v.length === 3 ? v.concat([1]) : v.slice(); }
    if (v.length < 2 || v.length > 3) fail(this.matchName + " needs 2 values, got " + JSON.stringify(v));
    return v.slice(0, 2);
  }
  get value() { return this.valueAtTime(0, false); }
  get numKeys() { return this.__keys.length; }
  get expression() { return this.__expr; }
  set expression(e) { if (typeof e !== "string") fail("expression must be a string"); this.__expr = e; }
  setValue(v) {
    if (this.__keys.length) fail("setValue on " + this.matchName + " which has keyframes");
    this.__value = this.__check(v);
  }
  setValueAtTime(t, v) {
    if (typeof t !== "number" || !isFinite(t)) fail("bad time " + t);
    const val = this.__check(v);
    const lt = t - this.__layer.startTime;
    const i = this.__keys.findIndex(k => Math.abs(k.t - lt) < 1e-6);
    const interp = DIMS[this.matchName] === "text" ? "hold" : "linear";
    if (i >= 0) this.__keys[i].v = val; else { this.__keys.push({ t: lt, v: val, interp }); this.__keys.sort((a, b) => a.t - b.t); }
  }
  setInterpolationTypeAtKey(i, inT, outT) {
    if (i < 1 || i > this.__keys.length) fail("key index " + i + " out of range");
    if (![6612, 6613, 6614].includes(inT)) fail("bad interpolation type");
    this.__keys[i - 1].interp = inT === 6614 ? "hold" : "linear";
  }
  valueAtTime(t, pre) {
    const v = this.__at(t - this.__layer.startTime);
    return v instanceof TextDocument ? v.clone() : (Array.isArray(v) ? v.slice() : v);
  }
  __at(lt) {
    const k = this.__keys;
    if (!k.length) return this.__value;
    if (lt <= k[0].t) return k[0].v;
    for (let i = 0; i < k.length - 1; i++) {
      if (lt >= k[i].t && lt < k[i + 1].t) {
        if (k[i].interp === "hold" || !Array.isArray(k[i].v) && typeof k[i].v !== "number") return k[i].v;
        const f = (lt - k[i].t) / (k[i + 1].t - k[i].t);
        if (typeof k[i].v === "number") return k[i].v + (k[i + 1].v - k[i].v) * f;
        return k[i].v.map((x, j) => x + (k[i + 1].v[j] - x) * f);
      }
    }
    return k[k.length - 1].v;
  }
  addToMotionGraphicsTemplateAs(comp, name) {
    if (!(comp instanceof CompItem) || comp !== this.__layer.containingComp) fail("Essential Graphics needs the layer's own comp");
    comp.__eg.push({ layer: this.__layer.name, name: String(name) });
    return true;
  }
  __json() { return { value: this.__value instanceof TextDocument ? Object.assign({}, this.__value) : this.__value, keys: this.__keys.map(k => ({ t: k.t, v: k.v instanceof TextDocument ? Object.assign({}, k.v) : k.v, interp: k.interp })), expression: this.__expr }; }
}

class Group {
  constructor(layer, matchName, children) { this.__layer = layer; this.matchName = matchName; this.__children = children || []; }
  property(key) {
    if (typeof key === "number") {
      if (key < 1 || key > this.__children.length) fail(this.matchName + ".property(" + key + ") out of range");
      return this.__children[key - 1];
    }
    const c = this.__children.find(x => x.matchName === key);
    if (!c) fail(this.matchName + " has no property \"" + key + "\"");
    return c;
  }
  get numProperties() { return this.__children.length; }
  addProperty(name) {
    const L = this.__layer;
    if (this.matchName === "ADBE Root Vectors Group" || this.matchName === "ADBE Vectors Group") {
      let g;
      if (name === "ADBE Vector Group") g = new Group(L, name, [new Group(L, "ADBE Vectors Group", [])]);
      else if (name === "ADBE Vector Shape - Rect") g = new Group(L, name, [new Property(L, "ADBE Vector Rect Size", [100, 100]), new Property(L, "ADBE Vector Rect Position", [0, 0]), new Property(L, "ADBE Vector Rect Roundness", 0)]);
      else if (name === "ADBE Vector Graphic - Fill") g = new Group(L, name, [new Property(L, "ADBE Vector Fill Color", [1, 0, 0, 1]), new Property(L, "ADBE Vector Fill Opacity", 100)]);
      else fail("can't add " + name + " to " + this.matchName);
      this.__children.push(g);
      return g;
    }
    fail("addProperty on " + this.matchName);
  }
}

// ------------------------------------------------------------------ layers
let nextId = 1;
class Layer {
  constructor(comp, kind) {
    this.__comp = comp; this.__kind = kind; this.__id = nextId++;
    this.__name = kind; this.inPointV = 0; this.outPointV = comp.duration; this.startTimeV = 0;
    this.__transform = new Group(this, "ADBE Transform Group", [
      new Property(this, "ADBE Anchor Point", [0, 0]), new Property(this, "ADBE Position", [960, 540]),
      new Property(this, "ADBE Scale", [100, 100]), new Property(this, "ADBE Opacity", 100)]);
  }
  get name() { return this.__name; }
  set name(v) { if (typeof v !== "string" || !v) fail("layer name must be a non-empty string"); this.__name = v; }
  get containingComp() { return this.__comp; }
  get inPoint() { return this.inPointV; }
  set inPoint(v) { if (!(v >= 0) || v >= this.outPointV) fail("inPoint " + v + " must be before outPoint " + this.outPointV + " (" + this.name + ")"); this.inPointV = v; }
  get outPoint() { return this.outPointV; }
  set outPoint(v) { if (!(v > this.inPointV)) fail("outPoint " + v + " must be after inPoint " + this.inPointV + " (" + this.name + ")"); this.outPointV = v; }
  get startTime() { return this.startTimeV; }
  set startTime(v) { const d = v - this.startTimeV; this.startTimeV = v; this.inPointV += d; this.outPointV += d; }
  get index() { return this.__comp.__layers.indexOf(this) + 1; }
  property(key) {
    if (key === "ADBE Transform Group") return this.__transform;
    const g = this.__groups && this.__groups[key];
    if (!g) fail(this.__kind + " layer has no \"" + key + "\"");
    return g;
  }
  moveAfter(other) {
    const a = this.__comp.__layers;
    if (other.__comp !== this.__comp) fail("moveAfter across comps");
    a.splice(a.indexOf(this), 1);
    a.splice(a.indexOf(other) + 1, 0, this);
  }
  sourceRectAtTime(t, ext) {
    if (this.__kind === "text") return textRect(this.__groups["ADBE Text Properties"].property("ADBE Text Document").valueAtTime(t, false));
    if (this.__kind === "shape") {
      const g = this.__groups["ADBE Root Vectors Group"];
      if (!g.numProperties) return { left: 0, top: 0, width: 0, height: 0 };
      const s = g.property(1).property("ADBE Vectors Group").property(1).property("ADBE Vector Rect Size").valueAtTime(t);
      return { left: -s[0] / 2, top: -s[1] / 2, width: s[0], height: s[1] };
    }
    if (this.__src && this.__src.width) return { left: 0, top: 0, width: this.__src.width, height: this.__src.height };
    return { left: 0, top: 0, width: 0, height: 0 };
  }
  __json() {
    const j = { id: this.__id, name: this.name, kind: this.__kind, inPoint: this.inPointV, outPoint: this.outPointV, startTime: this.startTimeV, transform: {} };
    this.__transform.__children.forEach(p => { j.transform[p.matchName] = p.__json(); });
    if (this.__kind === "text") j.text = this.__groups["ADBE Text Properties"].property("ADBE Text Document").__json();
    if (this.__kind === "shape") {
      const g = this.__groups["ADBE Root Vectors Group"].property(1).property("ADBE Vectors Group");
      j.size = g.property(1).property("ADBE Vector Rect Size").__json();
      j.color = g.property(2).property("ADBE Vector Fill Color").__json();
    }
    if (this.__src) j.source = this.__src.__ref();
    return j;
  }
}
class AVLayer extends Layer {}
class TextLayer extends AVLayer {}
class ShapeLayer extends AVLayer {}

class LayerCollection {
  constructor(comp) { this.__comp = comp; }
  __push(L) { this.__comp.__layers.unshift(L); return L; }
  addShape() {
    const L = new ShapeLayer(this.__comp, "shape");
    L.__groups = { "ADBE Root Vectors Group": new Group(L, "ADBE Root Vectors Group", []) };
    L.property("ADBE Transform Group").property("ADBE Position").__value = [960, 540];
    return this.__push(L);
  }
  addText(text) {
    if (typeof text !== "string") fail("addText expects a string here");
    const L = new TextLayer(this.__comp, "text");
    const d = new TextDocument(text);
    L.__groups = { "ADBE Text Properties": new Group(L, "ADBE Text Properties", [new Property(L, "ADBE Text Document", d)]) };
    return this.__push(L);
  }
  add(item, duration) {
    if (!(item instanceof FootageItem) && !(item instanceof CompItem)) fail("add() expects an item");
    const L = new AVLayer(this.__comp, item instanceof CompItem ? "precomp" : item.__audio ? "audio" : "image");
    L.__src = item;
    if (item.__audio) L.outPointV = item.duration;
    if (item instanceof CompItem) L.outPointV = Math.min(this.__comp.duration, item.duration);
    L.property("ADBE Transform Group").property("ADBE Anchor Point").__value = [item.width / 2 || 0, item.height / 2 || 0];
    return this.__push(L);
  }
  get length() { return this.__comp.__layers.length; }
}

// ------------------------------------------------------------------ items
let nextItem = 1;
class Item {
  constructor(name) { this.__id = nextItem++; this.__name = name; this.__parent = null; }
  get id() { return this.__id; }
  get name() { return this.__name; }
  set name(v) { this.__name = String(v); }
  get parentFolder() { return this.__parent || ROOT; }
  set parentFolder(f) {
    if (!(f instanceof FolderItem)) fail("parentFolder needs a folder");
    (this.__parent || ROOT).__items.splice((this.__parent || ROOT).__items.indexOf(this), 1);
    f.__items.push(this); this.__parent = f;
  }
}
class ItemCollection {
  constructor(folder) { this.__folder = folder; }
  addFolder(name) { const f = new FolderItem(String(name)); f.__parent = this.__folder === ROOT ? null : this.__folder; this.__folder.__items.push(f); return f; }
  addComp(name, w, h, pa, dur, fps) {
    if (w !== 1920 || h !== 1080 || pa !== 1 || fps !== 30) fail("unexpected comp settings " + [w, h, pa, fps]);
    if (!(dur > 0 && dur <= 3 * 3600)) fail("bad duration " + dur);
    const c = new CompItem(String(name), dur);
    c.__parent = this.__folder === ROOT ? null : this.__folder;
    this.__folder.__items.push(c);
    out.comps.push(c);
    return c;
  }
}
class FolderItem extends Item {
  constructor(name) { super(name); this.__items = []; }
  get items() { return new ItemCollection(this); }
  get numItems() { return this.__items.length; }
  item(i) { if (i < 1 || i > this.__items.length) fail("folder item index " + i); return this.__items[i - 1]; }
  __path() { return this.__parent ? this.__parent.__path() + "/" + this.name : this.name; }
}
class CompItem extends Item {
  constructor(name, dur) { super(name); this.duration = dur; this.width = 1920; this.height = 1080; this.frameRate = 30; this.__layers = []; this.__eg = []; this.__bg = [0, 0, 0]; }
  get layers() { return new LayerCollection(this); }
  get numLayers() { return this.__layers.length; }
  layer(i) { return typeof i === "number" ? this.__layers[i - 1] : this.__layers.find(l => l.name === i) || null; }
  get bgColor() { return this.__bg; }
  set bgColor(c) { this.__bg = c; }
  __ref() { return { comp: this.name }; }
  __json() {
    return { name: this.name, folder: this.__parent ? this.__parent.__path() : "", duration: this.duration, eg: this.__eg,
      layers: this.__layers.map(l => l.__json()) };
  }
}
class FootageItem extends Item {
  constructor(file) {
    super(path.basename(file));
    this.__file = file;
    if (/\.png$/i.test(file)) { const s = pngSize(file); this.width = s[0]; this.height = s[1]; this.__audio = false; }
    else if (/\.wav$/i.test(file)) { this.width = 0; this.height = 0; this.__audio = true; this.duration = wavSeconds(file); }
    else fail("unexpected import " + file);
  }
  get file() { return new File(this.__file); }
  __ref() { return { file: this.__file }; }
}
const ROOT = new FolderItem("Root");

function ImportOptions(file) { this.file = file || null; this.importAs = ImportAsType.FOOTAGE; this.sequence = false; }

const project = {
  get items() { return new ItemCollection(ROOT); },
  get numItems() { return ROOT.__items.length; },
  item(i) { return ROOT.item(i); },
  importFile(opts) {
    if (!(opts instanceof ImportOptions)) fail("importFile needs ImportOptions");
    if (!(opts.file instanceof File)) fail("ImportOptions needs a File");
    const f = opts.file.fsName;
    if (!fs.existsSync(f)) fail("import of a missing file " + f);
    const it = new FootageItem(f);
    ROOT.__items.push(it);
    out.imports.push(f);
    return it;
  },
};
let undoDepth = 0;
const app = {
  project,
  beginUndoGroup(n) { undoDepth++; },
  endUndoGroup() { if (undoDepth <= 0) fail("endUndoGroup without begin"); undoDepth--; },
};

// ------------------------------------------------------------------ ScriptUI (just enough for a message)
class Window {
  constructor(type, title) { if (type !== "dialog") fail("only dialogs"); this.__title = String(title); this.__lines = []; }
  add(kind, bounds, text) {
    if (!["statictext", "button"].includes(kind)) fail("unexpected control " + kind);
    if (kind === "statictext") this.__lines.push(String(text));
    return { kind, text };
  }
  show() { out.alerts.push(this.__lines.join("\n")); return 1; }
}

// ------------------------------------------------------------------ run
function expand(file, seen) {
  const dir = path.dirname(file);
  return fs.readFileSync(file, "utf8").split("\n").map(line => {
    const m = line.match(/^\s*#include\s+"([^"]+)"\s*;?\s*$/);
    if (!m) return line;
    const inc = path.resolve(dir, m[1]);
    if (seen.has(inc)) fail("include loop " + inc);
    return expand(inc, new Set([...seen, inc]));
  }).join("\n");
}

const sandbox = {
  $: { fileName: path.resolve(scriptPath), engineName: "boa", writeln: s => out.log.push(String(s)) },
  File, Folder, app, ImportOptions, ImportAsType, KeyframeInterpolationType, ParagraphJustification, TextDocument,
  FolderItem, CompItem, FootageItem, AVLayer, TextLayer, ShapeLayer, Window,
  alert: s => out.alerts.push(String(s)),
};
vm.createContext(sandbox);
const code = expand(path.resolve(scriptPath), new Set());
vm.runInContext(code, sandbox, { filename: path.basename(scriptPath) });
if (undoDepth !== 0) fail("undo group left open");
fs.writeFileSync(outPath, JSON.stringify({ comps: out.comps.map(c => c.__json()), alerts: out.alerts, log: out.log, imports: out.imports }, null, 1));
const failed = out.alerts.some(a => / stopped: /.test(a));
console.log((failed ? "FAILED " : "ok ") + path.basename(scriptPath) + ": " + out.comps.length + " comps" + (failed ? "\n" + out.alerts.join("\n") : ""));
process.exit(failed ? 1 : 0);
