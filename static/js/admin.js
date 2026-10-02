// Tracker admin helpers: copy a receipt's verify link to the clipboard.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('.lf-copy');
  if (!button) return;
  const original = button.textContent;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = 'Copied';
  } catch {
    button.textContent = 'Select and copy the link';
  }
  setTimeout(() => { button.textContent = original; }, 1800);
});
