"use strict";

const content = document.getElementById("content");
const source = document.getElementById("source");
const outline = document.getElementById("outline");
const notice = document.getElementById("notice");
const connection = document.getElementById("connection");
const renderedButton = document.getElementById("rendered-view");
const sourceButton = document.getElementById("source-view");
let digest = null;
let sourceVisible = false;
let observer = null;

function connectionState(label, live) {
  connection.textContent = label;
  connection.classList.toggle("live", live);
}

function selectView(showSource) {
  sourceVisible = showSource;
  source.hidden = !showSource;
  content.hidden = showSource;
  renderedButton.classList.toggle("selected", !showSource);
  sourceButton.classList.toggle("selected", showSource);
  renderedButton.setAttribute("aria-pressed", String(!showSource));
  sourceButton.setAttribute("aria-pressed", String(showSource));
}

function render(specification) {
  if (specification.state_digest === digest) return;
  const oldScroll = window.scrollY;
  const anchor = [...content.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]")]
    .reverse().find((heading) => heading.getBoundingClientRect().top <= 130);
  const anchorId = anchor?.id;
  const anchorOffset = anchor?.getBoundingClientRect().top;
  digest = specification.state_digest;
  document.title = `${specification.title} · Specification`;
  document.getElementById("revision").textContent = `Revision ${specification.revision}`;
  document.getElementById("counts").textContent = `${specification.node_count} nodes · ${specification.edge_count} relations`;
  // The only HTML insertion uses the server's Markdown renderer + strict sanitizer.
  content.innerHTML = specification.html;
  source.textContent = specification.markdown;
  outline.replaceChildren();
  for (const entry of specification.outline) {
    const link = document.createElement("a");
    link.href = `#${encodeURIComponent(entry.id)}`;
    link.textContent = entry.label;
    link.className = `outline-level-${Math.min(entry.level, 4)}`;
    link.addEventListener("click", () => {
      selectView(false);
      document.getElementById("outline-toggle").setAttribute("aria-expanded", "false");
      outline.classList.remove("expanded");
    });
    outline.append(link);
  }
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
  for (const heading of content.querySelectorAll("[id]")) observer.observe(heading);
  const replacement = anchorId ? document.getElementById(anchorId) : null;
  if (!sourceVisible && replacement && anchorOffset !== undefined) {
    window.scrollBy(0, replacement.getBoundingClientRect().top - anchorOffset);
  } else {
    window.scrollTo(0, oldScroll);
  }
}

renderedButton.addEventListener("click", () => selectView(false));
sourceButton.addEventListener("click", () => selectView(true));
document.getElementById("outline-toggle").addEventListener("click", (event) => {
  const expanded = event.currentTarget.getAttribute("aria-expanded") !== "true";
  event.currentTarget.setAttribute("aria-expanded", String(expanded));
  outline.classList.toggle("expanded", expanded);
});

const events = new EventSource("/events");
events.addEventListener("open", () => connectionState("Live", true));
events.addEventListener("specification", (event) => {
  try {
    render(JSON.parse(event.data));
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
window.addEventListener("pagehide", () => events.close());
