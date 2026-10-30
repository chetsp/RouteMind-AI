/* Presentation only: this preview never changes a result or submits a request. */
(() => {
  const choices = document.querySelectorAll('[data-preview]');
  if (!choices.length) return;
  let priority = 'cheapest';
  for (const button of choices) button.addEventListener('click', () => {
    priority = button.dataset.preview;
    const direct = priority === 'fastest';
    for (const choice of choices) choice.setAttribute('aria-pressed', String(choice === button));
    document.getElementById('preview-path').setAttribute('d', direct ? 'M75 65 Q210 25 312 128' : 'M75 65 Q125 66 189 114 Q250 145 312 128');
    document.getElementById('preview-transfer').setAttribute('opacity', direct ? '.25' : '1');
    document.getElementById('preview-route').textContent = direct ? 'Direct · No transfers' : 'Via Phoenix · 1 transfer';
    document.getElementById('preview-cost').textContent = direct ? '$3,400' : '$2,100';
    document.getElementById('preview-detail').textContent = direct ? '32 hours from scenario start · Prioritizes earlier arrival.' : '40 hours from scenario start · Includes transfer fee.';
  });
  document.getElementById('preview-use').addEventListener('click', () => {
    // Existing example handlers reset any prior conversation safely.
    document.querySelector(`[data-example="${priority}"]`).click();
    if (priority === 'fastest') document.getElementById('message').value = 'Find the fastest route for 15 pallets of fragile electronics from Fremont to Austin under $4,000.';
    document.getElementById('message').focus({preventScroll:true});
    document.getElementById('planner').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',block:'start'});
  });
})();
