(function () {
  if (window.MathJax && typeof window.MathJax.typesetPromise === "function") {
    return;
  }

  const commandMap = {
    "\\Omega": "Ω",
    "\\omega": "ω",
    "\\Delta": "Δ",
    "\\delta": "δ",
    "\\varphi": "φ",
    "\\phi": "φ",
    "\\theta": "θ",
    "\\Theta": "Θ",
    "\\alpha": "α",
    "\\beta": "β",
    "\\gamma": "γ",
    "\\lambda": "λ",
    "\\mu": "μ",
    "\\pi": "π",
    "\\infty": "∞",
    "\\angle": "∠",
    "\\times": "×",
    "\\cdot": "·",
    "\\pm": "±",
    "\\le": "≤",
    "\\ge": "≥",
    "\\neq": "≠",
    "\\approx": "≈",
  };

  function escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  }

  function replaceGroups(text, pattern, renderer) {
    let output = text;
    for (let i = 0; i < 12; i += 1) {
      const next = output.replace(pattern, renderer);
      if (next === output) break;
      output = next;
    }
    return output;
  }

  function renderLatex(raw) {
    let text = String(raw || "").trim();
    text = text
      .replace(/^\\\(|\\\)$/g, "")
      .replace(/^\\\[|\\\]$/g, "")
      .replace(/^\$\$|\$\$$/g, "")
      .replace(/^\$|\$$/g, "");

    let html = escapeHtml(text);
    html = replaceGroups(html, /\\frac\{([^{}]+)\}\{([^{}]+)\}/g, (_, top, bottom) => `<span class="math-frac"><span>${top}</span><span>${bottom}</span></span>`);
    html = replaceGroups(html, /\\sqrt\{([^{}]+)\}/g, (_, value) => `<span class="math-sqrt"><span>${value}</span></span>`);
    html = replaceGroups(html, /\\dot\{([^{}]+)\}/g, (_, value) => `<span class="math-dot">${value}</span>`);
    html = replaceGroups(html, /\\textcircled\{([^{}]+)\}/g, (_, value) => `<span class="math-circled">${value}</span>`);
    html = html.replace(/\\left|\\right/g, "");
    for (const [command, value] of Object.entries(commandMap)) {
      html = html.split(command).join(value);
    }
    html = html.replace(/([A-Za-z0-9)\]}ΩωΔδφθΘαβγλμπ])_\{([^{}]+)\}/g, "$1<sub>$2</sub>");
    html = html.replace(/([A-Za-z0-9)\]}ΩωΔδφθΘαβγλμπ])\^\{([^{}]+)\}/g, "$1<sup>$2</sup>");
    html = html.replace(/([A-Za-z0-9)\]}ΩωΔδφθΘαβγλμπ])_([A-Za-z0-9]+)/g, "$1<sub>$2</sub>");
    html = html.replace(/([A-Za-z0-9)\]}ΩωΔδφθΘαβγλμπ])\^([A-Za-z0-9+\-]+)/g, "$1<sup>$2</sup>");
    html = html.replace(/\\[,;:! ]/g, " ");
    html = html.replace(/\\/g, "");
    return `<span class="math-fallback-formula">${html}</span>`;
  }

  function replaceMathText(text) {
    const pattern = /(\\\([\s\S]+?\\\)|\\\[[\s\S]+?\\\]|\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
    const fragment = document.createDocumentFragment();
    let lastIndex = 0;
    let match;
    while ((match = pattern.exec(text))) {
      if (match.index > lastIndex) {
        fragment.appendChild(document.createTextNode(text.slice(lastIndex, match.index)));
      }
      const span = document.createElement("span");
      span.className = "math-fallback";
      span.innerHTML = renderLatex(match[0]);
      fragment.appendChild(span);
      lastIndex = pattern.lastIndex;
    }
    if (lastIndex < text.length) {
      fragment.appendChild(document.createTextNode(text.slice(lastIndex)));
    }
    return fragment;
  }

  function typesetElement(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        if (!parent || parent.closest("textarea, script, style, .math-fallback")) {
          return NodeFilter.FILTER_REJECT;
        }
        return /(\\\(|\\\[|\$\$|\$)/.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      node.replaceWith(replaceMathText(node.nodeValue));
    }
  }

  window.MathJax = window.MathJax || {};
  window.MathJax.typesetPromise = function (elements) {
    const targets = Array.isArray(elements) && elements.length ? elements : [document.body];
    for (const element of targets) {
      if (element) typesetElement(element);
    }
    return Promise.resolve();
  };
})();
