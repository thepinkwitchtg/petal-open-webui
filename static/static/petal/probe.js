// 🌸 petal · paint probe v0.1
// catches a primary button that lost her gradient, red-handed.
// sleeps until called — defines one function and touches nothing.
//
//   petalPaint()            → probe every primary button on screen
//   petalPaint('wash-off')  → same, with the ambient screen-wash muted (A/B)
//   petalPaint('wash-on')   → bring the wash back
//
// reading the verdict:
//   CSS-STOLEN  → computed background-image is none; the table names who took it
//   TOKEN-VOID  → --grad-fill is empty/invalid on that button
//   PAINT-GHOST → css is correct, the pixels are not → a compositor/raster glitch,
//                 not our cascade. the probe nudges a repaint so you can see if it heals.
(() => {
	if (window.petalPaint) return;

	const PRIMARY =
		"[class~='dark:bg-white'], [class~='dark:bg-gray-100'][class~='dark:text-gray-900']";

	// walk every rule we can reach — imports, layers, media, supports — remembering the layer path
	const walk = (rules, layer, out) => {
		for (const r of rules) {
			if (r.cssRules && r instanceof CSSLayerBlockRule)
				walk(r.cssRules, (layer ? layer + '.' : '') + (r.name || '(anon)'), out);
			else if (r instanceof CSSImportRule) {
				try {
					walk(r.styleSheet.cssRules, r.layerName ?? layer, out);
				} catch {}
			} else if (r instanceof CSSStyleRule) {
				out.push({ r, layer });
				if (r.cssRules?.length) walk(r.cssRules, layer, out); // nested
			} else if (r.cssRules) walk(r.cssRules, layer, out); // @media / @supports / @container
		}
		return out;
	};

	const allRules = () => {
		const out = [];
		for (const s of document.styleSheets) {
			try {
				walk(s.cssRules, null, out);
			} catch {
				out.push({ r: null, layer: '⚠ unreadable sheet: ' + (s.href || 'inline') });
			}
		}
		return out;
	};

	const PROPS = ['background', 'background-image', 'background-color'];

	const suspects = (el, rules) => {
		const hits = [];
		for (const { r, layer } of rules) {
			if (!r) continue;
			let ok = false;
			try {
				ok = el.matches(r.selectorText.replace(/::?[a-z-]+(\([^)]*\))?$/i, '') || '*');
			} catch {}
			if (!ok) continue;
			for (const p of PROPS) {
				const v = r.style.getPropertyValue(p);
				if (!v) continue;
				hits.push({
					prop: p,
					value: v.slice(0, 60),
					important: r.style.getPropertyPriority(p) === 'important',
					layer: layer ?? '(unlayered)',
					sheet: (r.parentStyleSheet?.href || 'inline').split('/').slice(-2).join('/'),
					selector: r.selectorText.slice(0, 90)
				});
			}
		}
		return hits;
	};

	const root = document.documentElement;

	window.petalPaint = (mode) => {
		if (mode === 'wash-off') root.classList.add('petal-no-wash');
		if (mode === 'wash-on') root.classList.remove('petal-no-wash');

		const btns = [...document.querySelectorAll(PRIMARY)].filter((b) => b.offsetParent);
		const rules = allRules();
		console.log(
			'%c🌸 petal paint probe',
			'color:#ff8fc8;font-weight:bold',
			'· html =',
			root.className,
			'· wash',
			root.classList.contains('petal-no-wash') ? 'muted' : 'on',
			'·',
			btns.length,
			'primary buttons'
		);

		btns.forEach((b, i) => {
			const cs = getComputedStyle(b);
			const img = cs.backgroundImage;
			const grad = cs.getPropertyValue('--grad-fill').trim();
			const verdict =
				img === 'none'
					? grad
						? 'CSS-STOLEN'
						: 'TOKEN-VOID'
					: grad
						? 'computed ok — look at it: dark = PAINT-GHOST'
						: 'TOKEN-VOID';
			const label = (b.textContent || b.getAttribute('aria-label') || '?').trim().slice(0, 24);
			console.groupCollapsed(`#${i} “${label}” → ${verdict}`);
			console.log('element', b);
			console.log('background-image:', img.slice(0, 90));
			console.log('background-color:', cs.backgroundColor, '· disabled:', b.disabled);
			console.log('--grad-fill:', grad ? grad.slice(0, 60) + '…' : '(empty)');
			console.log('opacity/filter/transform:', cs.opacity, cs.filter, cs.transform);
			console.table(suspects(b, rules));
			console.groupEnd();

			// gentle repaint nudge: if a PAINT-GHOST heals after this, the cascade was never the culprit
			// (background-position forces this button's own background to re-raster, nothing else)
			b.style.setProperty('background-position', '0 0.01px');
			requestAnimationFrame(() => b.style.removeProperty('background-position'));
		});

		return btns.length + ' probed — open the groups above 💗';
	};
})();
