// editor.js — a plain <textarea> with line numbers and a line highlight behind it.
//
// The highlight is a separate <div> positioned under the textarea (the textarea has
// a transparent background), so it can mark "the line running now" or "the line
// with the error" without changing the text.

export function createEditor({ textarea, gutter, highlight }) {
  const lineHeight = () => parseFloat(getComputedStyle(textarea).lineHeight);
  const paddingTop = () => parseFloat(getComputedStyle(textarea).paddingTop);
  let highlighted = null; // {line, kind}

  function renderGutter() {
    const count = textarea.value.split("\n").length;
    if (gutter.childElementCount === count) return;
    const frag = document.createDocumentFragment();
    for (let i = 1; i <= count; i++) {
      const div = document.createElement("div");
      div.textContent = i;
      frag.appendChild(div);
    }
    gutter.replaceChildren(frag);
    markGutter();
  }

  function markGutter() {
    for (const div of gutter.children) div.classList.remove("is-active", "is-error");
    if (highlighted) gutter.children[highlighted.line - 1]?.classList.add(`is-${highlighted.kind}`);
  }

  function syncScroll() {
    gutter.scrollTop = textarea.scrollTop;
    if (highlighted) {
      const top = paddingTop() + (highlighted.line - 1) * lineHeight() - textarea.scrollTop;
      highlight.style.transform = `translateY(${top}px)`;
    }
  }

  textarea.addEventListener("input", renderGutter);
  textarea.addEventListener("scroll", syncScroll);
  // Tab inserts four spaces instead of moving focus (Esc then Tab still leaves the editor).
  let escaped = false;
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { escaped = true; return; }
    if (e.key === "Tab" && !e.shiftKey && !escaped) {
      e.preventDefault();
      const { selectionStart: s, selectionEnd: end, value } = textarea;
      textarea.value = value.slice(0, s) + "    " + value.slice(end);
      textarea.selectionStart = textarea.selectionEnd = s + 4;
      renderGutter();
    }
    escaped = false;
  });

  return {
    getValue: () => textarea.value,
    setValue(text) {
      textarea.value = text;
      textarea.scrollTop = 0;
      renderGutter();
      this.clearHighlight();
    },
    /** Highlight one line. kind: "active" (playback) or "error". */
    highlightLine(line, kind = "active") {
      if (!line) return this.clearHighlight();
      highlighted = { line, kind };
      highlight.hidden = false;
      highlight.className = `editor__highlight editor__highlight--${kind}`;
      // Scroll the line into view if needed.
      const top = paddingTop() + (line - 1) * lineHeight();
      if (top < textarea.scrollTop || top + lineHeight() > textarea.scrollTop + textarea.clientHeight) {
        textarea.scrollTop = Math.max(0, top - textarea.clientHeight / 3);
      }
      markGutter();
      syncScroll();
    },
    clearHighlight() {
      highlighted = null;
      highlight.hidden = true;
      markGutter();
    },
  };
}
