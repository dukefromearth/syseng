"use strict";

const content = document.getElementById("content");
const source = document.getElementById("source");
const outline = document.getElementById("outline");
const notice = document.getElementById("notice");
const connection = document.getElementById("connection");
const renderedButton = document.getElementById("rendered-view");
const sourceButton = document.getElementById("source-view");
const inspectorButton = document.getElementById("inspector-view");
const search = document.getElementById("outline-search");
const readingControls = document.getElementById("reading-controls");
const DETAIL_SECTIONS = "details[data-section-id]:not(.diagram-source)";
const Surface = Object.freeze({DOCUMENT: "document", INSPECTOR: "inspector"});
let currentSurface = Surface.DOCUMENT;
let latestSpecification = null;
let digest = null;
let sourceVisible = false;
let observer = null;
let outlineEntries = [];
let diagramSequence = 0;
let renderGeneration = 0;
let diagramQueue = Promise.resolve();
const surfaceStates = new Map(Object.values(Surface).map((surface) => [surface, {
  disclosures: new Map(), search: "", scroll: 0,
}]));
const viewPositions = new Map();
let disclosureState = surfaceStates.get(currentSurface).disclosures;

function connectionState(label, live) {
  connection.textContent = label;
  connection.classList.toggle("live", live);
}

function selectView(showSource, restorePosition = true) {
  const changed = sourceVisible !== showSource;
  if (changed) viewPositions.set(sourceVisible ? `markdown:${currentSurface}` : currentSurface, window.scrollY);
  sourceVisible = showSource;
  source.hidden = !showSource;
  content.hidden = showSource;
  readingControls.hidden = showSource || !content.querySelector(DETAIL_SECTIONS);
  renderedButton.classList.toggle("selected", currentSurface === Surface.DOCUMENT);
  inspectorButton.classList.toggle("selected", currentSurface === Surface.INSPECTOR);
  inspectorButton.setAttribute("aria-pressed", String(currentSurface === Surface.INSPECTOR));
  sourceButton.classList.toggle("selected", showSource);
  renderedButton.setAttribute("aria-pressed", String(currentSurface === Surface.DOCUMENT));
  sourceButton.setAttribute("aria-pressed", String(showSource));
  if (changed && restorePosition) window.scrollTo(0, viewPositions.get(showSource ? `markdown:${currentSurface}` : currentSurface) || 0);
}

function rememberSurface() {
  const state = surfaceStates.get(currentSurface);
  state.search = search.value;
  state.scroll = sourceVisible ? (viewPositions.get(currentSurface) || 0) : window.scrollY;
  for (const section of content.querySelectorAll("details[data-section-id]")) {
    state.disclosures.set(section.dataset.sectionId, section.open);
  }
}

function switchSurface(surface) {
  if (!latestSpecification || (surface === Surface.INSPECTOR && !latestSpecification.inspector)) return;
  if (surface === currentSurface) { selectView(false); return; }
  rememberSurface();
  if (sourceVisible) viewPositions.set(`markdown:${currentSurface}`, window.scrollY);
  currentSurface = surface;
  sourceVisible = false;
  const state = surfaceStates.get(surface);
  disclosureState = state.disclosures;
  search.value = state.search;
  render(surface === Surface.INSPECTOR ? latestSpecification.inspector : latestSpecification,
    {replacingSurface: true, scroll: state.scroll});
}

function receiveSpecification(specification) {
  latestSpecification = specification;
  inspectorButton.hidden = !specification.inspector;
  if (currentSurface === Surface.INSPECTOR && !specification.inspector) {
    switchSurface(Surface.DOCUMENT);
  } else render(currentSurface === Surface.INSPECTOR ? specification.inspector : specification);
}

function revealTarget(hash, scroll = true) {
  let id;
  try { id = decodeURIComponent(hash.replace(/^#/, "")); }
  catch { return; }
  let target = document.getElementById(id);
  if (!target || !content.contains(target)) {
    if (currentSurface !== Surface.INSPECTOR
        && latestSpecification?.inspector?.outline.some((entry) => entry.id === id)) {
      switchSurface(Surface.INSPECTOR);
    } else if (currentSurface === Surface.INSPECTOR
        && (!id || latestSpecification?.outline.some((entry) => entry.id === id))) {
      switchSurface(Surface.DOCUMENT);
    }
    target = document.getElementById(id);
  }
  if (!target || !content.contains(target)) return;
  selectView(false);
  for (let ancestor = target; ancestor && ancestor !== content; ancestor = ancestor.parentElement) {
    if (ancestor.tagName === "DETAILS") {
      ancestor.open = true;
      if (ancestor.dataset.sectionId) disclosureState.set(ancestor.dataset.sectionId, true);
    }
  }
  if (scroll) requestAnimationFrame(() => target.scrollIntoView({block: "start"}));
}

function insideDisclosureBody(id) {
  const target = document.getElementById(id);
  const disclosure = target?.closest("details[data-section-id]");
  return disclosure && !disclosure.querySelector("summary")?.contains(target);
}

function renderOutline() {
  const query = search.value.trim().toLocaleLowerCase();
  outline.replaceChildren();
  const entries = outlineEntries.filter((entry) => query
    ? entry.label.toLocaleLowerCase().includes(query)
    : entry.level <= 3 && !insideDisclosureBody(entry.id));
  for (const entry of entries) {
    const link = document.createElement("a");
    link.href = `#${encodeURIComponent(entry.id)}`;
    link.textContent = entry.label;
    link.className = `outline-level-${Math.min(entry.level, 4)}`;
    link.addEventListener("click", () => {
      revealTarget(link.hash);
      document.getElementById("outline-toggle").setAttribute("aria-expanded", "false");
      outline.classList.remove("expanded");
    });
    outline.append(link);
  }
  if (!entries.length) {
    const empty = document.createElement("p");
    empty.className = "outline-empty";
    empty.textContent = "No matching sections";
    outline.append(empty);
  }
}

async function renderDiagrams(specification, generation) {
  const sectionState = disclosureState;
  for (const diagram of specification.diagrams || []) {
    if (generation !== renderGeneration) return;
    const figure = [...content.querySelectorAll("figure[data-diagram-id]")]
      .find((candidate) => candidate.dataset.diagramId === diagram.id);
    const canvas = figure?.querySelector(".diagram-canvas");
    if (!canvas) continue;
    const fallback = figure.querySelector("pre");
    try {
      if (!window.TypedGraphDiagrams) throw new Error("Diagram renderer unavailable");
      const svg = await window.TypedGraphDiagrams.render(
        `reader-diagram-${++diagramSequence}`, diagram.source, diagram.title,
      );
      if (generation !== renderGeneration || !canvas.isConnected) return;
      canvas.replaceChildren(svg);
      canvas.setAttribute("tabindex", "0");
      canvas.setAttribute("role", "region");
      canvas.setAttribute("aria-label", `${diagram.title}; scroll horizontally if needed`);
      figure.classList.add("diagram-ready");
      if (fallback) {
        const details = document.createElement("details");
        details.className = "diagram-source";
        details.dataset.sectionId = `diagram-source:${diagram.id}`;
        details.open = sectionState.get(details.dataset.sectionId) || false;
        details.addEventListener("toggle", () => {
          sectionState.set(details.dataset.sectionId, details.open);
        });
        const summary = document.createElement("summary");
        summary.textContent = "Inspect diagram source";
        details.append(summary, fallback);
        figure.append(details);
      }
    } catch {
      if (generation !== renderGeneration || !canvas.isConnected) return;
      canvas.textContent = "Diagram unavailable. Its graph-derived source is shown below.";
      canvas.classList.add("diagram-unavailable");
    }
  }
}

function render(specification, options = {}) {
  const nextDigest = `${currentSurface}:${specification.state_digest}`;
  if (nextDigest === digest && !options.replacingSurface) { selectView(sourceVisible); return; }
  const generation = ++renderGeneration;
  const sectionState = disclosureState;
  const oldScroll = options.replacingSurface ? options.scroll : window.scrollY;
  const anchor = [...content.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]")]
    .filter((heading) => heading.getClientRects().length)
    .reverse().find((heading) => heading.getBoundingClientRect().top <= 130);
  const anchorId = options.replacingSurface ? null : anchor?.id;
  const anchorOffset = anchor?.getBoundingClientRect().top;
  if (!options.replacingSurface) {
    for (const section of content.querySelectorAll("details[data-section-id]")) {
      disclosureState.set(section.dataset.sectionId, section.open);
    }
  }
  const initial = digest === null;
  digest = nextDigest;
  document.title = `${specification.title} · Specification`;
  document.getElementById("revision").textContent = `Revision ${specification.revision}`;
  document.getElementById("counts").textContent = currentSurface === Surface.DOCUMENT && latestSpecification?.inspector
    ? "Architectural specification" : `${specification.node_count} nodes · ${specification.edge_count} relations`;
  // The only document insertion uses the server's Markdown renderer + strict sanitizer.
  content.innerHTML = specification.html;
  source.textContent = specification.markdown;
  const inspector = currentSurface === Surface.INSPECTOR;
  source.setAttribute("aria-label", `${inspector ? "Graph inspector" : "Specification"} Markdown source`);
  const download = document.getElementById("download-markdown");
  download.href = inspector ? "/inspector.md" : "/specification.md";
  download.setAttribute("aria-label", `Download ${inspector ? "graph inspector" : "specification"} as Markdown`);
  for (const section of content.querySelectorAll("details[data-section-id]")) {
    if (disclosureState.has(section.dataset.sectionId)) {
      section.open = disclosureState.get(section.dataset.sectionId);
    }
    section.addEventListener("toggle", () => {
      sectionState.set(section.dataset.sectionId, section.open);
    });
  }
  outlineEntries = specification.outline;
  renderOutline();
  selectView(sourceVisible, false);
  notice.hidden = true;
  if (observer) observer.disconnect();
  observer = new window.IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      for (const link of outline.querySelectorAll("a")) {
        const selected = link.hash === `#${entry.target.id}`;
        link.classList.toggle("active", selected);
        if (selected) link.setAttribute("aria-current", "location");
        else link.removeAttribute("aria-current");
      }
    }
  }, {rootMargin: "-100px 0px -65% 0px"});
  for (const heading of content.querySelectorAll("h1[id],h2[id],h3[id]")) observer.observe(heading);
  if (initial && !options.replacingSurface && window.location.hash) revealTarget(window.location.hash);
  else {
    const replacement = anchorId ? document.getElementById(anchorId) : null;
    if (!sourceVisible && replacement && anchorOffset !== undefined) {
      window.scrollBy(0, replacement.getBoundingClientRect().top - anchorOffset);
    } else window.scrollTo(0, oldScroll);
  }
  // Serialize Mermaid's shared renderer, and discard results from superseded revisions.
  diagramQueue = diagramQueue.then(() => renderDiagrams(specification, generation));
}

content.addEventListener("click", (event) => {
  const link = event.target.closest("a[href^='#']");
  if (link) revealTarget(link.hash);
});
window.addEventListener("hashchange", () => revealTarget(window.location.hash));
search.addEventListener("input", () => {
  renderOutline();
  if (search.value.trim()) {
    outline.classList.add("expanded");
    document.getElementById("outline-toggle").setAttribute("aria-expanded", "true");
  }
});
for (const [id, expanded] of [["expand-details", true], ["collapse-details", false]]) {
  document.getElementById(id).addEventListener("click", () => {
    for (const section of content.querySelectorAll(DETAIL_SECTIONS)) {
      section.open = expanded;
      disclosureState.set(section.dataset.sectionId, expanded);
    }
  });
}
renderedButton.addEventListener("click", () => switchSurface(Surface.DOCUMENT));
sourceButton.addEventListener("click", () => selectView(!sourceVisible));
inspectorButton.addEventListener("click", () => switchSurface(Surface.INSPECTOR));
document.getElementById("outline-toggle").addEventListener("click", (event) => {
  const expanded = event.currentTarget.getAttribute("aria-expanded") !== "true";
  event.currentTarget.setAttribute("aria-expanded", String(expanded));
  outline.classList.toggle("expanded", expanded);
});

function connectEvents() {
const events = new EventSource("/events");
events.addEventListener("open", () => connectionState("Live", true));
events.addEventListener("specification", (event) => {
  try {
    receiveSpecification(JSON.parse(event.data));
    connectionState("Live", true);
  } catch {
    connectionState("Unable to display update", false);
  }
});
events.addEventListener("reader-status", (event) => {
  const status = JSON.parse(event.data);
  connectionState(status.state === "live" ? "Live" : "Update unavailable", status.state === "live");
  notice.hidden = status.state === "live" && digest !== null;
  notice.textContent = status.message;
});
events.addEventListener("error", () => {
  connectionState("Reconnecting", false);
  if (digest === null) notice.textContent = "Waiting for the local specification server. Reconnecting automatically…";
});
return events;
}
let events = connectEvents();
window.addEventListener("pagehide", () => events.close());
window.addEventListener("pageshow", (event) => {
  if (event.persisted && events.readyState === EventSource.CLOSED) events = connectEvents();
});
