/** Browser-only adapter. Inputs are generated diagram descriptors, never authored fences. */
import DOMPurify from "dompurify";

const mermaid = window.mermaid;

mermaid.initialize({
  startOnLoad: false,
  securityLevel: "strict",
  htmlLabels: false,
  suppressErrorRendering: true,
  maxTextSize: 50000,
  maxEdges: 200,
  theme: "base",
  fontFamily: "Arial, sans-serif",
  fontSize: 14,
  flowchart: {useMaxWidth: false, curve: "basis", nodeSpacing: 34, rankSpacing: 50},
});

/** Return a sanitized SVG element, with no script, external resource or inline style. */
export async function render(id, source, title) {
  const {svg} = await mermaid.render(id, source);
  const fragment = DOMPurify.sanitize(svg, {
    USE_PROFILES: {svg: true, svgFilters: false},
    RETURN_DOM_FRAGMENT: true,
    FORBID_TAGS: ["style", "foreignObject", "script", "image", "use", "a"],
    FORBID_ATTR: ["style", "href", "xlink:href"],
  });
  const element = fragment.querySelector("svg");
  if (!element) throw new Error("No diagram was rendered");
  // Marker and paint references must be same-document fragments, never URLs.
  for (const node of element.querySelectorAll("*")) {
    for (const attribute of [...node.attributes]) {
      if (/url\s*\(/i.test(attribute.value) && !/^url\(#[a-zA-Z0-9_-]+\)$/.test(attribute.value)) {
        node.removeAttribute(attribute.name);
      }
    }
  }
  // Mermaid's htmlLabels:false path can leave its label entities as literal text.
  // Decode exactly one layer on text nodes only. The projector escapes authored
  // ampersands/hash signs first, so literal authored entity sequences stay literal.
  const named = {amp: "&", lt: "<", gt: ">", quot: '"', apos: "'"};
  const walker = document.createTreeWalker(element, window.NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    walker.currentNode.textContent = walker.currentNode.textContent.replace(
      /&#([0-9]+);|&(amp|lt|gt|quot|apos);/g,
      (match, decimal, name) => {
        if (name) return named[name];
        const code = Number(decimal);
        return code > 0 && code <= 0x10ffff && !(code >= 0xd800 && code <= 0xdfff)
          ? String.fromCodePoint(code) : match;
      },
    );
  }
  element.setAttribute("role", "img");
  element.setAttribute("aria-label", title);
  element.removeAttribute("aria-roledescription");
  element.removeAttribute("aria-labelledby");
  element.removeAttribute("aria-describedby");
  element.removeAttribute("height");
  const width = Number(element.getAttribute("viewBox")?.split(/\s+/)[2]);
  element.setAttribute("width", String(Number.isFinite(width) ? Math.max(540, Math.min(width, 1600)) : 720));
  element.setAttribute("preserveAspectRatio", "xMidYMid meet");
  return element;
}
