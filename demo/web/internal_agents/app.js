// Presenter UI. It replays DATA (recorded from the real engine) and decides nothing itself.
// Every beat holds a full snapshot of the diagram, so stepping back and forward is just drawing.
const LABEL = {deny: "Deny", escalate: "Require human approval", auto_execute: "Allow automatically", observe: "Allow with monitoring"};
const ICON = {ok: "✓", fail: "✗", warn: "!", mon: "◉", skip: "–"};
const $ = id => document.getElementById(id);
const el = (t, c, x) => { const e = document.createElement(t); if (c) e.className = c; if (x !== undefined) e.textContent = x; return e; };
let scn = null, idx = 0, timer = null;

const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* storage unavailable */ } },
};

function rows(box, list, fresh) {
  const ul = $("b" + box).querySelector(".rows"); ul.replaceChildren();
  list.forEach((r, i) => {
    const li = el("li", r.s + (fresh ? " new" : "")); li.style.setProperty("--i", i);
    li.append(el("span", "ic", ICON[r.s]), el("span", 0, r.t));
    if (r.d) li.append(el("span", "d", r.d));
    ul.append(li);
  });
}

function place() {
  const b = scn.beats[idx], p = $("packet"), d = $("diagram").getBoundingClientRect();
  p.textContent = b.view.packet.text; p.className = "packet " + (b.view.packet.state || "");
  const at = b.view.packet.at, t = $(at).getBoundingClientRect(), w = p.offsetWidth;
  let x, y;
  if (at.startsWith("b")) { x = t.right - d.left - w - 14; y = t.top - d.top + 8; }
  else { x = Math.max(0, t.left - d.left + (t.width - w) / 2); y = t.bottom - d.top - 14; }
  p.style.transform = "translate(" + Math.round(x) + "px," + Math.round(y) + "px)";
}

function draw() {
  const b = scn.beats[idx], v = b.view;
  $("agent-name").textContent = v.agent.name; $("agent-ask").textContent = v.agent.ask;
  ["1", "2", "3"].forEach(n => {
    const box = $("b" + n), s = v.boxes[n].state;
    box.className = "pbox " + s + (b.active === n ? " on" : "");
    rows(n, v.boxes[n].rows, b.active === n);
  });
  $("agent").className = "card agent" + (b.active === "agent" ? " on" : "");
  $("system").className = "card sys st-" + v.system.state + (b.active === "system" ? " on" : "");
  $("system-text").textContent = v.system.text;
  $("review").className = "card rev st-" + v.review.state + (b.active === "review" ? " on" : "");
  $("review-text").textContent = v.review.text || "Only if needed";
  document.querySelectorAll(".tile").forEach(t => t.classList.toggle("lit", t.dataset.k === v.disp));
  $("head").textContent = b.head; $("sub").textContent = b.sub; $("tool").textContent = b.tool;
  const act = $("act"); act.textContent = b.act || ""; act.classList.toggle("hide", !b.act);
  renderRef(b);
  [...$("dots").children].forEach((d, i) => { d.classList.toggle("cur", i === idx); d.classList.toggle("seen", i < idx); });
  $("count").textContent = "Step " + (idx + 1) + " of " + scn.beats.length;
  $("prev").disabled = idx === 0; $("next").disabled = idx === scn.beats.length - 1;
  history.replaceState(null, "", "#" + scn.id + "/" + (idx + 1));
  place();
  if (idx === scn.beats.length - 1) stopAuto();
}

function table(body) {
  const t = el("table"), hr = el("tr");
  body.head.forEach(h => hr.append(el("th", 0, h))); t.append(hr);
  body.rows.forEach((r, i) => { const tr = el("tr", (body.mark || []).includes(i) ? "hit" : ""); r.forEach(c => tr.append(el("td", 0, String(c)))); t.append(tr); });
  return t;
}

function renderRef(b) {
  const box = $("ref"); box.replaceChildren();
  b.ref.forEach(it => {
    const w = el("div", "refitem"); w.append(el("h3", 0, it.title), el("p", 0, it.tech));
    const chips = el("div", "chips"); it.stack.forEach(s => chips.append(el("span", "chip", s))); w.append(chips);
    it.components.forEach(c => {
      const d = el("div", "comp"); d.append(document.createTextNode(c.port + " → "), el("span", "impl", c.impl), document.createTextNode("  " + JSON.stringify(c.config))); w.append(d);
    });
    it.artifacts.forEach(a => {
      const x = el("div", "art"); x.append(el("h4", 0, a.label), a.kind === "table" ? table(a.body) : el("pre", 0, a.body)); w.append(x);
    });
    box.append(w);
  });
}

function dots() {
  const d = $("dots"); d.replaceChildren(); let last = null;
  scn.beats.forEach((b, i) => {
    const x = el("button", "dot " + b.status + (b.act && b.act !== last && i ? " gap" : ""));
    x.title = (i + 1) + ". " + b.head; x.setAttribute("aria-label", "Step " + (i + 1) + ": " + b.head);
    x.onclick = () => go(i); d.append(x); last = b.act;
  });
}

function go(i) { idx = Math.max(0, Math.min(scn.beats.length - 1, i)); draw(); }

function open(s, step) {
  scn = s; idx = 0; stopAuto();
  $("picker").classList.add("hide"); $("stage").classList.remove("hide"); $("ctl").classList.remove("hide");
  $("scn-title").textContent = s.domain + ": " + s.title;
  dots(); go(step || 0); window.scrollTo(0, 0);
}

function picker() {
  scn = null; stopAuto(); history.replaceState(null, "", "#");
  $("stage").classList.add("hide"); $("ctl").classList.add("hide"); $("picker").classList.remove("hide");
  $("more").value = "";
}

function renderPicker() {
  const g = $("grid"); g.replaceChildren();
  DATA.scenarios.filter(s => s.core).forEach(s => {
    const c = el("button", "pick"); c.append(el("span", "dom", s.domain), el("b", 0, s.title), el("span", "t", s.blurb));
    c.append(el("span", "tag d-" + s.outcomes[0], LABEL[s.outcomes[0]])); c.onclick = () => open(s); g.append(c);
  });
  const m = $("more"); m.replaceChildren(el("option", 0, "Choose…")); m.firstChild.value = "";
  DATA.scenarios.filter(s => !s.core).forEach(s => { const o = el("option", 0, s.domain + ": " + s.title); o.value = s.id; m.append(o); });
  m.onchange = () => { const s = DATA.scenarios.find(x => x.id === m.value); if (s) open(s); };
  const d = $("disp"); d.replaceChildren();
  ["deny", "escalate", "auto_execute", "observe"].forEach(k => { const t = el("div", "tile " + k, LABEL[k]); t.dataset.k = k; d.append(t); });
}

function stopAuto() { clearTimeout(timer); timer = null; $("auto").checked = false; }
function tick() {
  if (!$("auto").checked || !scn) return;
  if (idx >= scn.beats.length - 1) return stopAuto();
  go(idx + 1); timer = setTimeout(tick, Number($("speed").value));
}

function setRef(on) { $("refmode").checked = on; $("ref").classList.toggle("hide", !on); store.set("ref", on ? "1" : "0"); }

$("refmode").onchange = () => setRef($("refmode").checked);
$("prev").onclick = () => { stopAuto(); go(idx - 1); };
$("next").onclick = () => { stopAuto(); go(idx + 1); };
$("change").onclick = picker;
$("auto").onchange = () => { clearTimeout(timer); if ($("auto").checked) timer = setTimeout(tick, Number($("speed").value)); };
window.addEventListener("resize", () => { if (scn) place(); });
document.addEventListener("keydown", e => {
  if (e.target.tagName === "SELECT" || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;
  if (k === "r" || k === "R") return setRef(!$("refmode").checked);
  if (!scn) return;
  if (k === "ArrowRight" || k === "PageDown" || (k === " " && e.target.tagName !== "BUTTON")) { e.preventDefault(); stopAuto(); go(idx + 1); }
  else if (k === "ArrowLeft" || k === "PageUp") { e.preventDefault(); stopAuto(); go(idx - 1); }
  else if (k === "Home") go(0);
  else if (k === "End") go(scn.beats.length - 1);
  else if (k === "Escape") picker();
});

(function init() {
  renderPicker(); setRef(store.get("ref") === "1");
  const m = /^#([\w-]+)\/(\d+)$/.exec(location.hash), s = m && DATA.scenarios.find(x => x.id === m[1]);
  if (s) open(s, Number(m[2]) - 1);
})();
