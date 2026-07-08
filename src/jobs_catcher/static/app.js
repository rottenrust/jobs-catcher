document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy-source]");
  if (!button) return;
  const id = button.getAttribute("data-copy-source");
  const source = document.querySelector(`[data-copy-target="${CSS.escape(id)}"]`);
  if (!source) return;
  const text = "value" in source ? source.value : source.textContent;
  try {
    await navigator.clipboard.writeText(text || "");
    button.dataset.copied = "true";
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = button.getAttribute("data-label") || "Copy"; }, 1200);
  } catch (_error) {
    if ("select" in source) { source.focus(); source.select(); }
  }
});
