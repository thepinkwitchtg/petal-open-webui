// 🌸 petal — theme registrar v0.2
// lives in an upstream-empty file. touches no components. rebase-proof.
(() => {
	if (window.__petalTheme) return;
	window.__petalTheme = true;

	const NAME = 'petal';
	const LABEL = '🌸 Petal';
	const META = '#0a0710'; // = --obsidian @ hue 301

	const root = document.documentElement;
	const isPetal = () => localStorage.getItem('theme') === NAME;

	const paint = () => {
		if (isPetal()) {
			// owui strips 'dark' when switching to an unknown theme value —
			// we put it back, because every dark: utility needs it.
			root.classList.add('dark', NAME);
			// their applyTheme writes these four inline; inline beats our
			// stylesheet, so clear them and let the token layer speak.
			['800', '850', '900', '950'].forEach((k) => root.style.removeProperty('--color-gray-' + k));
			const m = document.querySelector('meta[name="theme-color"]');
			if (m) m.setAttribute('content', META);
		} else {
			root.classList.remove(NAME); // owui won't clean up after us
		}
	};

	window.applyTheme = paint; // their hook, our hands

	const graft = (sel) => {
		// identified by its options, not its label — survives i18n and renames
		if (!sel.querySelector('option[value="oled-dark"]')) return;
		if (sel.querySelector('option[value="' + NAME + '"]')) return;
		const opt = document.createElement('option');
		opt.value = NAME;
		opt.textContent = LABEL;
		sel.appendChild(opt);
		if (isPetal()) sel.value = NAME;
		console.log('🌸 petal: grafted into theme select');
	};

	const sweep = () => document.querySelectorAll('select').forEach(graft);

	// three nets, because one silent failure is enough
	new MutationObserver((muts) => {
		for (const m of muts)
			for (const n of m.addedNodes) {
				if (n.nodeType !== 1) continue; // skip streaming text nodes
				if (n.tagName === 'SELECT') graft(n);
				else if (n.querySelectorAll) n.querySelectorAll('select').forEach(graft);
			}
	}).observe(root, { childList: true, subtree: true });

	document.addEventListener('click', () => setTimeout(sweep, 120), true);
	document.addEventListener('DOMContentLoaded', () => {
		paint();
		sweep();
	});

	paint();
	console.log('🌸 petal registrar alive — theme is', localStorage.getItem('theme'));
})();
