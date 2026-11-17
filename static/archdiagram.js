/* Architecture diagram for the hero section: grouped modules, labelled edges, RAG highlighted. */
(function () {
  'use strict';

  var REPO = 'https://github.com/mithun50/ragbot';
  var MERMAID_SRC = 'https://cdn.jsdelivr.net/npm/mermaid@10.9.3/dist/mermaid.min.js';

  var DEFINITION = [
    'flowchart TB',
    '  user(("User")):::person',
    '  subgraph UI["User interface"]',
    '    web["Web interface<br/>[app.js]"]:::plain',
    '    api["HTTP API<br/>[main.py]"]:::plain',
    '  end',
    '  subgraph ING["Document ingestion"]',
    '    ingest["Ingestion worker<br/>[ingest.py]"]:::plain',
    '    parse["Document parsing<br/>[parsing.py]"]:::plain',
    '    chunk["Page chunking<br/>[chunking.py]"]:::plain',
    '    summ["Document summaries<br/>[summarize.py]"]:::plain',
    '  end',
    '  subgraph RAG["RAG ENGINE: grounded question answering"]',
    '    qa["QA orchestration<br/>[qa.py]"]:::rag',
    '    cache["Answer cache"]:::ragsoft',
    '    expand["Query expansion"]:::ragsoft',
    '    bm25["BM25 retrieval<br/>[index.py]"]:::rag',
    '    fuse["Rank fusion and MMR"]:::ragsoft',
    '    gate{"Relevance gate"}:::rag',
    '    ctx["Context builder<br/>with neighbours"]:::ragsoft',
    '    prompts["Grounding prompts<br/>[prompts.py]"]:::ragsoft',
    '    llmc["Model client<br/>[llm.py]"]:::rag',
    '    cite["Citation validation"]:::ragsoft',
    '  end',
    '  subgraph DATA["Storage and insight"]',
    '    store[("Index store<br/>[data/docs]")]:::plain',
    '    an["Analytics<br/>[analytics.py]"]:::plain',
    '  end',
    '  ext["OpenRouter models<br/>Ling 3.2 Flash, Particle 1"]:::plain',
    '  user -->|uses| web',
    '  web -->|requests| api',
    '  api -->|starts ingestion| ingest',
    '  api -->|streams answers| qa',
    '  api -->|serves analytics| an',
    '  ingest -->|reads pages| parse',
    '  ingest -->|chunks pages| chunk',
    '  ingest -->|requests summary| summ',
    '  chunk -->|saves chunks| store',
    '  qa -->|checks| cache',
    '  qa -->|expands| expand',
    '  expand -->|searches| bm25',
    '  bm25 -->|reads| store',
    '  bm25 -->|candidates| fuse',
    '  fuse -->|top passages| gate',
    '  gate -->|"too weak: NOT_FOUND"| qa',
    '  gate -->|relevant| ctx',
    '  ctx -->|formats with| prompts',
    '  prompts -->|messages| llmc',
    '  llmc -->|streams from| ext',
    '  llmc -->|answer| cite',
    '  cite -->|cited answer| api',
    '  qa -->|records| an',
    '  summ -->|uses| llmc',
    '  classDef person fill:#FFFFFF,stroke:#111111,stroke-width:2px,color:#111111',
    '  classDef plain fill:#F2F2F2,stroke:#9A9A9A,stroke-width:1px,color:#222222',
    '  classDef ragsoft fill:#FFFFFF,stroke:#111111,stroke-width:2px,color:#111111',
    '  classDef rag fill:#111111,stroke:#111111,stroke-width:2px,color:#FFFFFF',
    '  style UI fill:#FAFAFA,stroke:#CFCFCF',
    '  style ING fill:#FAFAFA,stroke:#CFCFCF',
    '  style DATA fill:#FAFAFA,stroke:#CFCFCF',
    '  style RAG fill:#FFFFFF,stroke:#111111,stroke-width:3px'
  ].join('\n');

  var DARK_DEFINITION = DEFINITION
    .replace('classDef person fill:#FFFFFF,stroke:#111111,stroke-width:2px,color:#111111', 'classDef person fill:#1E1E1E,stroke:#F2F2F2,stroke-width:2px,color:#F2F2F2')
    .replace('classDef plain fill:#F2F2F2,stroke:#9A9A9A,stroke-width:1px,color:#222222', 'classDef plain fill:#232323,stroke:#5A5A5A,stroke-width:1px,color:#E6E6E6')
    .replace('classDef ragsoft fill:#FFFFFF,stroke:#111111,stroke-width:2px,color:#111111', 'classDef ragsoft fill:#1A1A1A,stroke:#F2F2F2,stroke-width:2px,color:#F2F2F2')
    .replace('classDef rag fill:#111111,stroke:#111111,stroke-width:2px,color:#FFFFFF', 'classDef rag fill:#F2F2F2,stroke:#F2F2F2,stroke-width:2px,color:#111111')
    .replace('style UI fill:#FAFAFA,stroke:#CFCFCF', 'style UI fill:#141414,stroke:#3A3A3A')
    .replace('style ING fill:#FAFAFA,stroke:#CFCFCF', 'style ING fill:#141414,stroke:#3A3A3A')
    .replace('style DATA fill:#FAFAFA,stroke:#CFCFCF', 'style DATA fill:#141414,stroke:#3A3A3A')
    .replace('style RAG fill:#FFFFFF,stroke:#111111,stroke-width:3px', 'style RAG fill:#0E0E0E,stroke:#F2F2F2,stroke-width:3px');

  var cache = { light: null, dark: null };
  var loading = null;
  var seq = 0;

  function isDark() { return document.documentElement.getAttribute('data-theme') === 'dark'; }

  function loadMermaid() {
    if (window.mermaid) return Promise.resolve(window.mermaid);
    if (loading) return loading;
    loading = new Promise(function (resolve, reject) {
      var s = document.createElement('script');
      s.src = MERMAID_SRC;
      s.onload = function () { resolve(window.mermaid); };
      s.onerror = function () { loading = null; reject(new Error('Could not load the diagram library')); };
      document.head.appendChild(s);
    });
    return loading;
  }

  function render() {
    var dark = isDark(), key = dark ? 'dark' : 'light';
    if (cache[key]) return Promise.resolve(cache[key]);
    return loadMermaid().then(function (m) {
      m.initialize({
        startOnLoad: false, securityLevel: 'strict', theme: 'base',
        flowchart: { htmlLabels: true, curve: 'basis', nodeSpacing: 36, rankSpacing: 56, padding: 10 },
        themeVariables: {
          fontFamily: 'Inter, system-ui, sans-serif', fontSize: '14px',
          lineColor: dark ? '#9A9A9A' : '#555555',
          edgeLabelBackground: dark ? '#0E0E0E' : '#FFFFFF',
          background: dark ? '#0E0E0E' : '#FFFFFF'
        }
      });
      return m.render('ragarch' + (++seq), dark ? DARK_DEFINITION : DEFINITION);
    }).then(function (r) { cache[key] = r.svg; return r.svg; });
  }

  function iconsRefresh() { if (window.lucide && window.lucide.createIcons) window.lucide.createIcons(); }

  /* ---------- pan and zoom viewer ---------- */
  function Viewer(stage, opts) {
    var s = { x: 0, y: 0, k: 1 }, drag = null;
    var inner = document.createElement('div');
    inner.className = 'arch-inner';
    stage.appendChild(inner);
    function apply() { inner.style.transform = 'translate(' + s.x + 'px,' + s.y + 'px) scale(' + s.k + ')'; }
    function zoomAt(f, cx, cy) {
      var nk = Math.min(4, Math.max(0.25, s.k * f)), r = nk / s.k;
      s.x = cx - (cx - s.x) * r; s.y = cy - (cy - s.y) * r; s.k = nk; apply();
    }
    function fit() {
      var svg = inner.querySelector('svg');
      if (!svg) return;
      var vb = svg.viewBox && svg.viewBox.baseVal;
      var w = vb && vb.width ? vb.width : svg.getBoundingClientRect().width;
      var h = vb && vb.height ? vb.height : svg.getBoundingClientRect().height;
      var sw = stage.clientWidth, sh = stage.clientHeight;
      s.k = Math.min(sw / w, sh / h) * 0.96; if (opts && opts.fitWidth) s.k = (sw / w) * 0.98;
      s.x = (sw - w * s.k) / 2; s.y = opts && opts.fitWidth ? 0 : (sh - h * s.k) / 2; apply();
    }
    stage.addEventListener('wheel', function (e) {
      if (!opts || !opts.wheel) return;
      e.preventDefault();
      var b = stage.getBoundingClientRect();
      zoomAt(e.deltaY < 0 ? 1.12 : 1 / 1.12, e.clientX - b.left, e.clientY - b.top);
    }, { passive: false });
    stage.addEventListener('pointerdown', function (e) {
      if (!opts || !opts.drag) return;
      drag = { x: e.clientX - s.x, y: e.clientY - s.y }; stage.setPointerCapture(e.pointerId); stage.classList.add('is-grab');
    });
    stage.addEventListener('pointermove', function (e) { if (drag) { s.x = e.clientX - drag.x; s.y = e.clientY - drag.y; apply(); } });
    function up() { drag = null; stage.classList.remove('is-grab'); }
    stage.addEventListener('pointerup', up);
    stage.addEventListener('pointercancel', up);
    return {
      set: function (svg) {
        inner.innerHTML = svg;
        var el = inner.querySelector('svg');
        if (el) { el.removeAttribute('style'); el.style.maxWidth = 'none'; el.style.display = 'block'; var vb = el.viewBox.baseVal; if (vb && vb.width) { el.setAttribute('width', vb.width); el.setAttribute('height', vb.height); } }
        requestAnimationFrame(fit);
      },
      zoomIn: function () { zoomAt(1.25, stage.clientWidth / 2, stage.clientHeight / 2); },
      zoomOut: function () { zoomAt(1 / 1.25, stage.clientWidth / 2, stage.clientHeight / 2); },
      fit: fit
    };
  }

  function exportSvg() {
    render().then(function (svg) {
      var blob = new Blob([svg], { type: 'image/svg+xml' });
      var a = document.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'ragbot-architecture.svg';
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
    });
  }

  /* ---------- hero card ---------- */
  var heroViewer = null, overlay = null, overlayViewer = null;

  function mount(host) {
    if (!host) return;
    host.innerHTML =
      '<div class="arch-head">' +
        '<div class="arch-title"><i data-lucide="network"></i><span>How RagBot is built</span><em>RAG engine highlighted</em></div>' +
        '<div class="arch-actions">' +
          '<a class="arch-chip" href="' + REPO + '" target="_blank" rel="noopener"><i data-lucide="github"></i>mithun50/ragbot</a>' +
          '<button type="button" class="arch-btn" data-act="expand"><i data-lucide="maximize-2"></i>Expand</button>' +
        '</div>' +
      '</div>' +
      '<div class="arch-stage" id="arch-stage"><div class="arch-loading">Drawing the architecture</div></div>';
    iconsRefresh();
    host.querySelector('[data-act="expand"]').addEventListener('click', openOverlay);
    var stage = host.querySelector('#arch-stage');
    stage.addEventListener('click', function (e) { if (!e.target.closest('a')) openOverlay(); });
    heroViewer = Viewer(stage, { fitWidth: true });
    render().then(function (svg) {
      stage.querySelector('.arch-loading') && stage.querySelector('.arch-loading').remove();
      heroViewer.set(svg);
    }).catch(function (err) {
      stage.innerHTML = '<div class="arch-loading">' + String(err.message || err).replace(/</g, '&lt;') + '. Check your connection and reload.</div>';
    });
  }

  function openOverlay() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'arch-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-label', 'RagBot architecture diagram');
    overlay.innerHTML =
      '<div class="arch-bar">' +
        '<div class="arch-title"><i data-lucide="network"></i><span>RagBot architecture</span><em>Scroll to zoom, drag to move</em></div>' +
        '<div class="arch-actions">' +
          '<a class="arch-chip" href="' + REPO + '" target="_blank" rel="noopener"><i data-lucide="github"></i>mithun50/ragbot</a>' +
          '<button type="button" class="arch-btn" data-act="out" aria-label="Zoom out"><i data-lucide="zoom-out"></i></button>' +
          '<button type="button" class="arch-btn" data-act="in" aria-label="Zoom in"><i data-lucide="zoom-in"></i></button>' +
          '<button type="button" class="arch-btn" data-act="fit"><i data-lucide="scan"></i>Fit</button>' +
          '<button type="button" class="arch-btn" data-act="export"><i data-lucide="download"></i>Export SVG</button>' +
          '<button type="button" class="arch-btn is-solid" data-act="close"><i data-lucide="x"></i>Close</button>' +
        '</div>' +
      '</div>' +
      '<div class="arch-stage arch-stage-full"></div>';
    document.body.appendChild(overlay);
    iconsRefresh();
    overlayViewer = Viewer(overlay.querySelector('.arch-stage'), { wheel: true, drag: true });
    render().then(function (svg) { if (overlayViewer) overlayViewer.set(svg); });
    overlay.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act]'); if (!b) return;
      var a = b.getAttribute('data-act');
      if (a === 'close') closeOverlay();
      else if (a === 'in') overlayViewer.zoomIn();
      else if (a === 'out') overlayViewer.zoomOut();
      else if (a === 'fit') overlayViewer.fit();
      else if (a === 'export') exportSvg();
    });
    document.addEventListener('keydown', onKey);
  }
  function onKey(e) { if (e.key === 'Escape') closeOverlay(); }
  function closeOverlay() {
    if (!overlay) return;
    overlay.remove(); overlay = null; overlayViewer = null;
    document.removeEventListener('keydown', onKey);
  }

  // Redraw in the new palette when the theme toggles.
  new MutationObserver(function () {
    if (heroViewer || overlayViewer) {
      render().then(function (svg) {
        if (heroViewer) heroViewer.set(svg);
        if (overlayViewer) overlayViewer.set(svg);
      });
    }
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  window.RagArch = { mount: mount, open: openOverlay };
})();
