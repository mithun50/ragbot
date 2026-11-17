/* RagBot frontend. No build step, no dependencies besides Lucide icons. */
(function () {
  'use strict';

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  var ALLOWED = ['pdf', 'docx', 'txt', 'md', 'markdown', 'csv', 'json', 'html', 'htm'];
  var STOP = ('a an the and or of to in on for with is are was were be been it its this that these those what which who whom how why when where ' +
    'do does did can could should would will about from by as at into than then there their they them you your i me my we our us not no').split(' ');
  var GENERIC_Q = [
    ['sparkles', 'Summarize the key points of my documents'],
    ['list-checks', 'What are the main conclusions or recommendations?'],
    ['clock', 'List important dates, numbers, or deadlines'],
    ['book-open', 'Which topics are covered in the most detail?']
  ];

  var LOGO = '<svg viewBox="0 0 32 32" aria-hidden="true"><rect class="lg-b" x="1" y="1" width="30" height="30" rx="9"/><rect class="lg-w" x="6" y="12.6" width="20" height="6.8" rx="2.4" opacity=".2"/><rect class="lg-w" x="8.5" y="8" width="15" height="2.6" rx="1.3"/><rect class="lg-w" x="8.5" y="14.7" width="10.5" height="2.6" rx="1.3"/><rect class="lg-w" x="8.5" y="21.4" width="13" height="2.6" rx="1.3" opacity=".5"/></svg>';

  var state = {
    docs: [], docsLoaded: false, excluded: new Set(), open: null, config: null, view: 'chat',
    convs: [], cur: null, rts: {}, activeTurn: null, activeN: null,
    busy: false, abort: null, pollTimer: null, anTimer: null, seq: 0, stick: true, anPrev: {}
  };

  function store(key, val) {
    try {
      if (val === undefined) return localStorage.getItem(key);
      localStorage.setItem(key, val);
    } catch (e) { /* storage unavailable */ }
    return null;
  }
  try {
    var ex = JSON.parse(store('ragbot.excluded') || '[]');
    if (Array.isArray(ex)) state.excluded = new Set(ex);
    var cv = JSON.parse(store('ragbot.convs') || '[]');
    if (Array.isArray(cv)) state.convs = cv;
  } catch (e) { /* ignore */ }

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function icons() { try { if (window.lucide) window.lucide.createIcons(); } catch (e) { /* ignore */ } }
  function icon(name, cls) { return '<i data-lucide="' + name + '"' + (cls ? ' class="' + cls + '"' : '') + '></i>'; }
  function fmtInt(n) { return (Number(n) || 0).toLocaleString('en-US'); }
  function fmtBytes(b) {
    b = Number(b) || 0;
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(0) + ' KB';
    if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
    return (b / 1073741824).toFixed(2) + ' GB';
  }
  function fmtMs(ms) {
    ms = Number(ms) || 0;
    return ms >= 1000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms) + ' ms';
  }
  function ext(name) { var m = /\.([^.]+)$/.exec(name || ''); return m ? m[1].toLowerCase() : ''; }
  function timeAgo(ts) {
    var t = new Date(ts).getTime();
    if (!t) return '';
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.floor(s / 60) + ' min ago';
    if (s < 86400) return Math.floor(s / 3600) + ' h ago';
    return Math.floor(s / 86400) + ' d ago';
  }
  function clamp01(x) { x = Number(x) || 0; return x < 0 ? 0 : x > 1 ? 1 : x; }
  function has(v) { return v !== undefined && v !== null && v !== ''; }
  function debounce(fn, ms) { var t; return function () { var a = arguments; clearTimeout(t); t = setTimeout(function () { fn.apply(null, a); }, ms); }; }
  function jfetch(url, opts) {
    return fetch(url, opts).then(function (r) {
      return r.text().then(function (txt) {
        var data = null;
        try { data = txt ? JSON.parse(txt) : null; } catch (e) { /* not json */ }
        if (!r.ok) {
          var d = data && data.detail;
          if (Array.isArray(d)) d = d.map(function (x) { return x.msg || ''; }).join(', ');
          var err = new Error(d || ('Request failed (' + r.status + ')'));
          err.status = r.status;
          throw err;
        }
        return data;
      });
    });
  }

  /* ---------- toasts and tooltips ---------- */
  function toast(msg, kind) {
    var wrap = $('#toasts');
    var el = document.createElement('div');
    el.className = 'toast' + (kind === 'err' ? ' err' : '');
    el.innerHTML = '<span class="t-ico">' + icon(kind === 'err' ? 'circle-alert' : 'circle-check') + '</span>' +
      '<div class="t-msg">' + esc(msg) + '</div>' +
      '<button class="icon-btn small" aria-label="Dismiss notification">' + icon('x') + '</button>';
    wrap.appendChild(el);
    icons();
    var gone = false;
    function close() {
      if (gone) return; gone = true;
      el.classList.add('out');
      setTimeout(function () { el.remove(); }, 260);
    }
    $('button', el).addEventListener('click', close);
    setTimeout(close, kind === 'err' ? 7000 : 3500);
    while (wrap.children.length > 4) wrap.firstChild.remove();
  }

  var tipEl = null;
  function showTip(target, text) {
    if (!tipEl) { tipEl = document.createElement('div'); tipEl.className = 'tip'; tipEl.setAttribute('role', 'tooltip'); document.body.appendChild(tipEl); }
    tipEl.textContent = text;
    tipEl.classList.add('show');
    var r = target.getBoundingClientRect ? target.getBoundingClientRect() : target;
    var w = tipEl.offsetWidth, h = tipEl.offsetHeight;
    var x = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var y = r.bottom + 8;
    if (y + h > window.innerHeight - 8) y = r.top - h - 8;
    tipEl.style.transform = 'translate(' + Math.round(x) + 'px,' + Math.round(y) + 'px)';
  }
  function hideTip() { if (tipEl) tipEl.classList.remove('show'); }
  function tipText(el) {
    if (el.dataset && el.dataset.tip) return el.dataset.tip;
    if (el.matches && el.matches('.icon-btn, .send')) return el.getAttribute('aria-label') || '';
    return '';
  }
  function setupTips() {
    document.addEventListener('mouseover', function (e) {
      var el = e.target.closest && e.target.closest('[data-tip], .icon-btn[aria-label], .send[aria-label]');
      if (!el || el.disabled) return;
      var t = tipText(el);
      if (t) showTip(el, t);
    });
    document.addEventListener('mouseout', function (e) { if (e.target.closest && e.target.closest('[data-tip], .icon-btn, .send')) hideTip(); });
    document.addEventListener('focusin', function (e) {
      var el = e.target; var t = el.matches && el.matches('[data-tip], .icon-btn[aria-label]') ? tipText(el) : '';
      if (t && el.matches(':focus-visible')) showTip(el, t);
    });
    document.addEventListener('focusout', hideTip);
    document.addEventListener('click', hideTip, true);
    document.addEventListener('scroll', hideTip, true);
  }

  /* ---------- config and model menu ---------- */
  function loadConfig() {
    return jfetch('/api/config').then(function (c) {
      state.config = c;
      var ok = !!c.llm_configured;
      $('#model-dot').className = 'dot ' + (ok ? 'ok' : 'warn');
      var dismissed = store('ragbot.banner') === '1';
      $('#banner').hidden = ok || dismissed;
      renderModelMenu();
    }).catch(function () {
      $('#model-dot').className = 'dot';
      $('#model-text').textContent = 'Offline';
    });
  }
  function modelList() {
    var c = state.config || {};
    var models = (c.models || []).map(function (m) { return typeof m === 'string' ? m : (m.id || m.name || ''); }).filter(Boolean);
    if (c.model && models.indexOf(c.model) < 0) models.unshift(c.model);
    return models;
  }
  function activeModel() {
    var c = state.config || {}, saved = store('ragbot.model');
    return saved && modelList().indexOf(saved) >= 0 ? saved : (c.model || '');
  }
  function renderModelMenu() {
    var c = state.config || {}, models = modelList(), active = activeModel();
    $('#model-text').textContent = c.llm_configured ? (active || 'Model ready') : 'No API key';
    $('#model-menu').innerHTML = '<div class="menu-label">Choose a model</div>' + (models.length ? models.map(function (m) {
      var act = m === active;
      return '<div class="menu-item' + (act ? ' is-active' : '') + '" role="option" tabindex="0" data-model="' + esc(m) + '" aria-selected="' + act + '">' + (act ? icon('check') : '<span class="ph"></span>') + '<span title="' + esc(m) + '">' + esc(m) + '</span></div>';
    }).join('') : '<div class="menu-item"><span class="ph"></span><span>No models listed</span></div>') +
      '<div class="menu-label foot">' + esc((c.app_name || 'RagBot') + (c.version ? ' v' + c.version : '')) + '</div>';
    icons();
  }
  function setupModelMenu() {
    var pill = $('#model-pill'), menu = $('#model-menu');
    function close() { menu.hidden = true; pill.setAttribute('aria-expanded', 'false'); }
    function pick(e) {
      var it = e.target.closest && e.target.closest('[data-model]');
      if (!it) return;
      store('ragbot.model', it.getAttribute('data-model'));
      renderModelMenu();
      close();
      if (typeof toast === 'function') toast('Using ' + it.getAttribute('data-model'));
    }
    menu.addEventListener('click', pick);
    menu.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(e); } });
    pill.addEventListener('click', function (e) {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      pill.setAttribute('aria-expanded', menu.hidden ? 'false' : 'true');
    });
    document.addEventListener('click', function (e) { if (!menu.hidden && !menu.contains(e.target)) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !menu.hidden) close(); });
  }

  /* ---------- documents ---------- */
  var docEls = {};
  function readyDocs() { return state.docs.filter(function (d) { return d.status === 'ready'; }); }
  function includedDocs() { return readyDocs().filter(function (d) { return !state.excluded.has(d.id); }); }
  function includedIds() { return includedDocs().map(function (d) { return d.id; }); }
  function saveExcluded() { store('ragbot.excluded', JSON.stringify(Array.from(state.excluded))); }
  function isBusyStatus(s) { return s !== 'ready' && s !== 'error'; }

  function loadDocs() {
    return jfetch('/api/documents').then(function (r) {
      state.docs = (r && r.documents) || [];
      state.docsLoaded = true;
      renderDocs();
      schedulePoll();
    }).catch(function (e) {
      if (!state.docsLoaded) { state.docsLoaded = true; renderDocs(); }
      schedulePoll();
      if (!loadDocs.warned) { loadDocs.warned = true; toast('Could not load documents. ' + e.message, 'err'); }
    });
  }
  function schedulePoll() {
    var need = state.docs.some(function (d) { return isBusyStatus(d.status); });
    if (need && !state.pollTimer) {
      state.pollTimer = setInterval(function () {
        loadDocs().then(function () {
          if (!state.docs.some(function (d) { return isBusyStatus(d.status); })) { clearInterval(state.pollTimer); state.pollTimer = null; }
        });
      }, 1000);
    } else if (!need && state.pollTimer) { clearInterval(state.pollTimer); state.pollTimer = null; }
  }
  function statusLabel(d) {
    return { queued: 'Queued', parsing: 'Reading', indexing: 'Indexing', summarizing: 'Summarizing', ready: 'Ready', error: 'Failed' }[d.status] || d.status;
  }

  function buildDocEl(d) {
    var li = document.createElement('li');
    li.className = 'doc';
    li.dataset.id = d.id;
    li.innerHTML =
      '<div class="doc-main">' +
        '<label class="check"><input type="checkbox" aria-label="Include in search"><span class="box"><svg class="lucide" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg></span></label>' +
        '<button class="doc-info" type="button" aria-expanded="false"><span class="doc-name"></span><span class="doc-meta"></span></button>' +
        '<div class="doc-actions">' +
          '<button class="icon-btn small tog" type="button" aria-label="Show summary">' + icon('chevron-down', 'chev') + '</button>' +
          '<button class="icon-btn small del" type="button" aria-label="Delete document">' + icon('trash-2') + '</button>' +
        '</div>' +
      '</div>' +
      '<div class="doc-progress" hidden><div class="bar"><span></span></div></div>' +
      '<div class="doc-err" hidden></div>' +
      '<div class="detail"><div><div class="detail-inner"></div></div></div>';
    var cb = $('input', li);
    cb.addEventListener('change', function () {
      if (cb.checked) state.excluded.delete(d.id); else state.excluded.add(d.id);
      saveExcluded();
      li.classList.toggle('is-off', !cb.checked);
      updateScope();
    });
    function toggle() { state.open = state.open === li.dataset.id ? null : li.dataset.id; updateOpen(); }
    $('.doc-info', li).addEventListener('click', toggle);
    $('.tog', li).addEventListener('click', toggle);

    var del = $('.del', li), timer = null;
    function reset() {
      del.classList.remove('confirm');
      del.innerHTML = icon('trash-2');
      del.setAttribute('aria-label', 'Delete document');
      icons();
    }
    del.addEventListener('click', function () {
      if (!del.classList.contains('confirm')) {
        del.classList.add('confirm');
        del.innerHTML = icon('trash-2') + '<span>Delete?</span>';
        del.setAttribute('aria-label', 'Confirm delete');
        icons();
        timer = setTimeout(reset, 3500);
        return;
      }
      clearTimeout(timer);
      del.disabled = true;
      jfetch('/api/documents/' + encodeURIComponent(li.dataset.id), { method: 'DELETE' }).then(function () {
        state.docs = state.docs.filter(function (x) { return x.id !== li.dataset.id; });
        state.excluded.delete(li.dataset.id);
        saveExcluded();
        li.style.transition = 'opacity .2s, transform .2s';
        li.style.opacity = '0'; li.style.transform = 'scale(.97)';
        setTimeout(function () { delete docEls[li.dataset.id]; li.remove(); renderDocs(); }, 190);
        toast('Document removed');
      }).catch(function (e) { del.disabled = false; reset(); toast(e.message, 'err'); });
    });
    return li;
  }

  function updateDocEl(li, d) {
    var ready = d.status === 'ready';
    $('.doc-name', li).textContent = d.filename;
    $('.doc-name', li).title = d.filename;
    var cb = $('input', li);
    cb.disabled = !ready;
    cb.checked = ready && !state.excluded.has(d.id);
    li.classList.toggle('is-off', ready && !cb.checked);

    var cls = ready ? 'ready' : d.status === 'error' ? 'error' : 'busy';
    var meta = '<span class="status ' + cls + '">' + esc(statusLabel(d)) + '</span>';
    if (ready) {
      meta += '<span class="mono">' + fmtInt(d.pages_total || d.pages_done) + ' pp</span><span class="mono">' + fmtInt(d.chunks) + ' chunks</span>';
    } else if (d.status !== 'error') {
      if (d.pages_total) meta += '<span class="mono">' + fmtInt(d.pages_done) + '/' + fmtInt(d.pages_total) + ' pp</span>';
      else if (d.chunks) meta += '<span class="mono">' + fmtInt(d.chunks) + ' chunks</span>';
    } else meta += '<span class="mono">' + esc(fmtBytes(d.size_bytes)) + '</span>';
    $('.doc-meta', li).innerHTML = meta;

    var prog = $('.doc-progress', li);
    var showProg = isBusyStatus(d.status);
    prog.hidden = !showProg;
    if (showProg) {
      var bar = $('.bar', prog), fill = $('span', bar), pct = null;
      if (d.status === 'summarizing') pct = 100;
      else if (d.pages_total > 0) pct = Math.min(100, Math.round((d.pages_done / d.pages_total) * 100));
      bar.classList.toggle('indeterminate', pct === null || d.status === 'summarizing');
      if (pct !== null && d.status !== 'summarizing') fill.style.width = pct + '%'; else fill.style.width = '';
      prog.setAttribute('role', 'progressbar');
      prog.setAttribute('aria-label', 'Processing ' + d.filename);
      if (pct !== null) prog.setAttribute('aria-valuenow', String(pct)); else prog.removeAttribute('aria-valuenow');
    }
    var errEl = $('.doc-err', li);
    errEl.hidden = d.status !== 'error';
    if (d.status === 'error') errEl.textContent = d.error || 'Processing failed';

    var inner = $('.detail-inner', li);
    var sig = ready ? JSON.stringify([d.summary, d.key_facts, d.suggested_questions]) : '';
    if (inner.dataset.sig !== sig) {
      inner.dataset.sig = sig;
      if (!ready) inner.innerHTML = '';
      else {
        var h = '';
        if (d.summary) h += '<div class="d-label">Summary</div><p class="d-summary">' + esc(d.summary) + '</p>';
        if (d.key_facts && d.key_facts.length) h += '<div class="d-label">Key facts</div><ul class="d-facts">' + d.key_facts.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('') + '</ul>';
        if (d.suggested_questions && d.suggested_questions.length) {
          h += '<div class="d-label">Try asking</div><div class="d-chips">' + d.suggested_questions.map(function (q) { return '<button class="qchip" type="button" data-q="' + esc(q) + '">' + esc(q) + '</button>'; }).join('') + '</div>';
        }
        inner.innerHTML = h || '<p class="d-summary">No summary available.</p>';
        $$('.qchip', inner).forEach(function (b) { b.addEventListener('click', function () { askQuestion(b.dataset.q); }); });
      }
    }
  }

  function updateOpen() {
    Object.keys(docEls).forEach(function (id) {
      var li = docEls[id], open = state.open === id;
      li.classList.toggle('is-open', open);
      $('.doc-info', li).setAttribute('aria-expanded', open ? 'true' : 'false');
      $('.tog', li).setAttribute('aria-label', open ? 'Hide summary' : 'Show summary');
    });
  }

  function renderDocs() {
    var list = $('#doc-list');
    $('#doc-skeleton').hidden = state.docsLoaded;
    $('#doc-count').textContent = state.docs.length;
    $('#doc-empty').hidden = !state.docsLoaded || state.docs.length > 0;
    var seen = {};
    state.docs.forEach(function (d, i) {
      seen[d.id] = true;
      var li = docEls[d.id];
      if (!li) li = docEls[d.id] = buildDocEl(d);
      updateDocEl(li, d);
      var at = list.children[i];
      if (at !== li) list.insertBefore(li, at || null);
    });
    Object.keys(docEls).forEach(function (id) { if (!seen[id]) { docEls[id].remove(); delete docEls[id]; } });
    updateOpen();
    updateScope();
    icons();
  }

  function updateScope() {
    var ready = readyDocs(), inc = includedDocs();
    // An empty scope is never useful: default back to every ready document.
    if (ready.length && !inc.length) { state.excluded.clear(); saveExcluded(); inc = includedDocs(); }
    var el = $('#scope'), h = '';
    if (!ready.length) {
      h = '<span class="schip muted">' + icon('paperclip') + '<span>' + (state.docs.length ? 'Documents are being prepared' : 'No documents yet. Attach a file to begin') + '</span></span>';
    } else if (!inc.length) {
      h = '<span class="schip muted">' + icon('files') + '<span>No documents selected</span></span>';
    } else {
      h = inc.slice(0, 4).map(function (d) {
        return '<span class="schip">' + icon('file-text') + '<span title="' + esc(d.filename) + '">' + esc(d.filename) + '</span><button type="button" data-ex="' + esc(d.id) + '" aria-label="Exclude ' + esc(d.filename) + ' from search">' + icon('x') + '</button></span>';
      }).join('') + (inc.length > 4 ? '<span class="schip muted"><span>+' + (inc.length - 4) + ' more</span></span>' : '');
    }
    if (el.dataset.sig !== h) {
      el.dataset.sig = h;
      el.innerHTML = h;
      $$('button[data-ex]', el).forEach(function (b) {
        b.addEventListener('click', function () { state.excluded.add(b.dataset.ex); saveExcluded(); renderDocs(); });
      });
      icons();
    }
    renderWelcome();
    updateSendState();
  }

  /* ---------- upload ---------- */
  function handleFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []);
    if (!files.length) return;
    var ok = [], bad = [];
    files.forEach(function (f) { (ALLOWED.indexOf(ext(f.name)) >= 0 ? ok : bad).push(f); });
    if (bad.length) toast('Unsupported file type: ' + bad.map(function (f) { return f.name; }).join(', '), 'err');
    if (ok.length) upload(ok);
  }
  function openDocsSection() {
    var sec = $('#docs-sec');
    sec.classList.remove('is-collapsed');
    $('#docs-toggle').setAttribute('aria-expanded', 'true');
  }

  function upload(files) {
    openDocsSection();
    var ul = $('#uploads');
    var li = document.createElement('li');
    li.className = 'upload-item';
    var label = files.length === 1 ? files[0].name : files.length + ' files';
    li.innerHTML = '<div class="u-top"><span class="u-name">' + esc(label) + '</span><span class="u-pct">0%</span></div><div class="bar"><span></span></div>';
    ul.appendChild(li);
    var fill = $('.bar span', li), pct = $('.u-pct', li), bar = $('.bar', li);
    var fd = new FormData();
    files.forEach(function (f) { fd.append('files', f, f.name); });
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/documents');
    xhr.upload.onprogress = function (e) {
      if (!e.lengthComputable) { bar.classList.add('indeterminate'); return; }
      var p = Math.round((e.loaded / e.total) * 100);
      fill.style.width = p + '%'; pct.textContent = p >= 100 ? 'Saving' : p + '%';
      if (p >= 100) bar.classList.add('indeterminate');
    };
    function finish() { setTimeout(function () { li.remove(); }, 400); }
    xhr.onload = function () {
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300 && data && data.documents) {
        var added = data.documents, ids = {};
        added.forEach(function (d) { ids[d.id] = true; });
        state.docs = added.concat(state.docs.filter(function (d) { return !ids[d.id]; }));
        renderDocs(); schedulePoll();
        toast(added.length === 1 ? 'Uploaded ' + added[0].filename : 'Uploaded ' + added.length + ' files');
      } else {
        var msg = data && data.detail;
        if (Array.isArray(msg)) msg = msg.map(function (x) { return x.msg; }).join(', ');
        toast(msg || 'Upload failed (' + xhr.status + ')', 'err');
      }
      finish();
    };
    xhr.onerror = function () { toast('Upload failed. Check your connection.', 'err'); finish(); };
    xhr.send(fd);
  }

  function setupUpload() {
    var dz = $('#dropzone'), input = $('#file-input');
    var ov = document.createElement('div');
    ov.className = 'drop-overlay'; ov.hidden = true;
    ov.innerHTML = '<div class="drop-box">' + icon('cloud-upload') + '<div class="drop-t">Drop to upload</div><div class="drop-s">PDF, DOCX, TXT, MD, CSV, JSON, HTML</div></div>';
    document.body.appendChild(ov);
    dz.addEventListener('click', function () { input.click(); });
    dz.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
    $('#btn-attach').addEventListener('click', function () { input.click(); });
    input.addEventListener('change', function () { handleFiles(input.files); input.value = ''; });
    var depth = 0;
    function isFiles(e) { return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0; }
    document.addEventListener('dragenter', function (e) { if (!isFiles(e)) return; e.preventDefault(); depth++; ov.hidden = false; icons(); });
    document.addEventListener('dragover', function (e) { if (isFiles(e)) e.preventDefault(); });
    document.addEventListener('dragleave', function (e) { if (!isFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) ov.hidden = true; });
    document.addEventListener('drop', function (e) {
      if (!isFiles(e)) return;
      e.preventDefault(); depth = 0; ov.hidden = true;
      if (state.view !== 'chat') setView('chat');
      handleFiles(e.dataTransfer.files);
    });
  }

  /* ---------- markdown-lite (safe) ---------- */
  function inline(text, nSources) {
    var codes = [];
    var t = String(text).replace(/`([^`\n]+)`/g, function (m, c) { codes.push(c); return '\u0000' + (codes.length - 1) + '\u0000'; });
    t = esc(t);
    t = t.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    t = t.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    t = t.replace(/\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]/g, function (m, grp) {
      return grp.split(',').map(function (s) {
        var n = parseInt(s, 10);
        if (nSources != null && (n < 1 || n > nSources)) return '<span class="cite is-off" title="Passage not available">' + n + '</span>';
        return '<button type="button" class="cite" data-n="' + n + '" aria-label="Open source ' + n + '">' + n + '</button>';
      }).join('');
    });
    return t.replace(/\u0000(\d+)\u0000/g, function (m, i) { return '<code>' + esc(codes[+i]) + '</code>'; });
  }
  function renderMarkdown(src, nSources) {
    var lines = String(src).replace(/\r/g, '').split('\n');
    var html = '', para = [], list = null;
    function flushPara() { if (para.length) { html += '<p>' + para.map(function (l) { return inline(l, nSources); }).join('<br>') + '</p>'; para = []; } }
    function closeList() { if (list) { html += '</' + list + '>'; list = null; } }
    lines.forEach(function (line) {
      var m;
      if (!line.trim()) { flushPara(); closeList(); return; }
      if ((m = /^\s*[-*•]\s+(.*)$/.exec(line))) {
        flushPara();
        if (list !== 'ul') { closeList(); html += '<ul>'; list = 'ul'; }
        html += '<li>' + inline(m[1], nSources) + '</li>';
      } else if ((m = /^\s*(\d+)[.)]\s+(.*)$/.exec(line))) {
        flushPara();
        if (list !== 'ol') { closeList(); html += '<ol>'; list = 'ol'; }
        html += '<li>' + inline(m[2], nSources) + '</li>';
      } else if ((m = /^\s{0,3}#{1,4}\s+(.*)$/.exec(line))) {
        flushPara(); closeList();
        html += '<p class="md-h">' + inline(m[1], nSources) + '</p>';
      } else { closeList(); para.push(line); }
    });
    flushPara(); closeList();
    return html;
  }

  /* ---------- highlight ---------- */
  function queryTerms(q) {
    var words = String(q).toLowerCase().match(/[a-z0-9À-ɏ]+/g) || [];
    var out = [];
    words.forEach(function (w) {
      if (w.length < 3 || STOP.indexOf(w) >= 0) return;
      var stem = w.replace(/(ing|ed|es|s)$/, '');
      if (stem.length < 3) stem = w;
      if (out.indexOf(stem) < 0) out.push(stem);
    });
    return out;
  }
  function highlight(text, terms) {
    if (!terms.length) return esc(text);
    var re;
    try { re = new RegExp('(\\b(?:' + terms.map(function (t) { return t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }).join('|') + ')[\\wÀ-ɏ]*)', 'gi'); } catch (e) { return esc(text); }
    return String(text).split(re).map(function (part, i) { return i % 2 ? '<mark>' + esc(part) + '</mark>' : esc(part); }).join('');
  }

  /* ---------- panels ---------- */
  function isOverlay() { return window.matchMedia('(max-width: 1180px)').matches; }
  function isNarrow() { return window.matchMedia('(max-width: 900px)').matches; }
  function syncScrim() {
    var app = $('#app');
    var show = (isOverlay() && app.classList.contains('sources-open')) || (isNarrow() && app.classList.contains('sidebar-open'));
    $('#scrim').hidden = !show;
  }
  function sourcesVisible() { var a = $('#app'); return isOverlay() ? a.classList.contains('sources-open') : !a.classList.contains('no-sources'); }
  function openSources() {
    var app = $('#app');
    if (isOverlay()) app.classList.add('sources-open'); else app.classList.remove('no-sources');
    $('#btn-sources').setAttribute('aria-expanded', 'true'); syncScrim();
  }
  function closeSources() {
    var app = $('#app');
    if (isOverlay()) app.classList.remove('sources-open'); else app.classList.add('no-sources');
    $('#btn-sources').setAttribute('aria-expanded', 'false'); syncScrim();
  }
  function sidebarVisible() { var a = $('#app'); return isNarrow() ? a.classList.contains('sidebar-open') : !a.classList.contains('no-sidebar'); }
  function toggleSidebar(force) {
    var app = $('#app'), show = force === undefined ? !sidebarVisible() : force;
    if (isNarrow()) app.classList.toggle('sidebar-open', show); else app.classList.toggle('no-sidebar', !show);
    $('#btn-sidebar').setAttribute('aria-expanded', show ? 'true' : 'false'); syncScrim();
  }

  function renderSources(rt, activeN, opts) {
    opts = opts || {};
    var list = $('#src-list');
    var t = rt && rt.t;
    state.activeTurn = t ? t.id : null; state.activeN = activeN || null;
    Object.keys(state.rts).forEach(function (id) { state.rts[id].el.classList.toggle('is-selected', !!t && +id === t.id); });
    var srcs = (t && t.sources) || [];
    $('#src-empty').hidden = srcs.length > 0;
    if (!srcs.length) { list.innerHTML = ''; delete list.dataset.turn; $('#src-sub').textContent = t ? 'No passages were retrieved' : 'Passages behind the selected answer'; return; }
    $('#src-sub').textContent = srcs.length + ' passage' + (srcs.length === 1 ? '' : 's') + ' retrieved';
    if (list.dataset.turn !== String(t.id) || list.dataset.count !== String(srcs.length)) {
      list.dataset.turn = String(t.id); list.dataset.count = String(srcs.length);
      var smx = Math.max.apply(null, srcs.map(function (s) { return s.score || 0; }).concat([0.0001]));
      list.innerHTML = srcs.map(function (s, i) {
        var rel = clamp01((s.score || 0) / smx);
        return '<li class="src" id="src-' + s.n + '" data-n="' + s.n + '" style="animation-delay:' + Math.min(i, 8) * 40 + 'ms">' +
          '<div class="src-top"><span class="src-n">' + s.n + '</span><span class="src-file" title="' + esc(s.filename) + '">' + esc(s.filename) + '</span><span class="src-page">p.' + esc(s.page) + '</span></div>' +
          (s.heading ? '<div class="src-sec" title="' + esc(s.heading) + '">' + esc(s.heading) + '</div>' : '') +
          '<div class="rel"><div class="bar"><span style="width:' + Math.round(rel * 100) + '%"></span></div><span class="rel-v">' + rel.toFixed(2) + '</span></div>' +
          '<div class="src-text">' + highlight(s.text, rt.terms) + '</div></li>';
      }).join('');
    }
    $$('.src', list).forEach(function (el) { el.classList.toggle('is-active', +el.dataset.n === state.activeN); });
    if (opts.scroll && activeN) {
      var el = $('#src-' + activeN, list);
      if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash'); }
    }
  }
  function citeClick(rt, n) { if (!rt) return; openSources(); renderSources(rt, n, { scroll: true }); }

  /* ---------- conversations ---------- */
  function saveConvs() {
    // History must survive reloads: store a compact copy (short passages) and drop only the oldest chats if storage is full.
    function compact(c) {
      return Object.assign({}, c, { turns: c.turns.map(function (t) {
        return Object.assign({}, t, { steps: [], sources: (t.sources || []).map(function (s) { return Object.assign({}, s, { text: String(s.text || '').slice(0, 600) }); }) });
      }) });
    }
    var list = state.convs.map(compact);
    for (;;) {
      try { localStorage.setItem('ragbot.convs', JSON.stringify(list)); return; } catch (e) {
        if (list.length <= 1) return;
        list.pop();
      }
    }
  }
  function sortConvs() { state.convs.sort(function (a, b) { return (b.updated || 0) - (a.updated || 0); }); }
  function makeTitle(q) { q = q.replace(/\s+/g, ' ').trim(); return q.length > 48 ? q.slice(0, 47) + '...' : q; }

  function renderHistory() {
    var list = $('#hist-list'), term = $('#hist-search').value.trim().toLowerCase();
    var items = state.convs.filter(function (c) {
      if (!term) return true;
      return c.title.toLowerCase().indexOf(term) >= 0 || c.turns.some(function (t) { return t.q.toLowerCase().indexOf(term) >= 0; });
    });
    var empty = $('#hist-empty');
    empty.hidden = items.length > 0;
    empty.textContent = term ? 'No chats match your search.' : 'Your conversations will appear here.';
    list.innerHTML = '';
    items.forEach(function (c) {
      var li = document.createElement('li');
      li.className = 'hist-item' + (state.cur && state.cur.id === c.id ? ' is-active' : '');
      li.innerHTML = '<button type="button" class="hist-title"></button><div class="hist-actions">' +
        '<button type="button" class="icon-btn small ren" aria-label="Rename chat">' + icon('pencil') + '</button>' +
        '<button type="button" class="icon-btn small del" aria-label="Delete chat">' + icon('trash-2') + '</button></div>';
      var tb = $('.hist-title', li);
      tb.textContent = c.title; tb.title = c.title;
      tb.addEventListener('click', function () { openConv(c.id); if (isNarrow()) toggleSidebar(false); });
      $('.ren', li).addEventListener('click', function () {
        var inp = document.createElement('input');
        inp.className = 'hist-edit'; inp.value = c.title; inp.setAttribute('aria-label', 'Chat name');
        tb.replaceWith(inp); $('.hist-actions', li).hidden = true; inp.focus(); inp.select();
        var done = false;
        function commit(save) {
          if (done) return; done = true;
          if (save && inp.value.trim()) { c.title = inp.value.trim().slice(0, 80); saveConvs(); }
          renderHistory();
        }
        inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') commit(true); else if (e.key === 'Escape') commit(false); });
        inp.addEventListener('blur', function () { commit(true); });
      });
      var del = $('.del', li), timer = null;
      del.addEventListener('click', function () {
        if (!del.classList.contains('confirm')) {
          del.classList.add('confirm'); del.innerHTML = '<span>Delete?</span>'; del.setAttribute('aria-label', 'Confirm delete chat');
          timer = setTimeout(function () { renderHistory(); }, 3000);
          return;
        }
        clearTimeout(timer);
        state.convs = state.convs.filter(function (x) { return x.id !== c.id; });
        saveConvs();
        if (state.cur && state.cur.id === c.id) newChat(); else renderHistory();
      });
      list.appendChild(li);
    });
    icons();
  }

  function openConv(id) {
    var c = state.convs.filter(function (x) { return x.id === id; })[0];
    if (!c) return;
    if (state.view !== 'chat') setView('chat');
    if (state.abort) state.abort.abort();
    state.cur = c;
    resetThread();
    c.turns.forEach(function (t) { var rt = buildTurn(t); paintFinal(rt); });
    refreshActions();
    renderWelcome();
    renderHistory();
    scrollDown(true);
  }

  function resetThread() {
    Object.keys(state.rts).forEach(function (id) { clearInterval(state.rts[id].timer); });
    state.rts = {}; state.activeTurn = null; state.activeN = null;
    $('#thread').innerHTML = '';
    var l = $('#src-list'); l.innerHTML = ''; delete l.dataset.turn; delete l.dataset.count;
    $('#src-empty').hidden = false;
    $('#src-sub').textContent = 'Passages behind the selected answer';
  }

  function newChat() {
    if (state.abort) state.abort.abort();
    if (state.view !== 'chat') setView('chat');
    state.cur = null;
    resetThread();
    renderWelcome();
    renderHistory();
    updateSendState();
    $('#composer-input').focus();
  }

  /* ---------- welcome ---------- */
  function renderWelcome() {
    var thread = $('#thread');
    var empty = !state.cur || state.cur.turns.length === 0;
    var w = $('#welcome');
    if (!empty) { if (w) w.remove(); return; }
    var ready = readyDocs();
    var qs = [];
    includedDocs().forEach(function (d) { (d.suggested_questions || []).slice(0, 2).forEach(function (q) { if (qs.indexOf(q) < 0) qs.push(q); }); });
    var cards = qs.slice(0, 4).map(function (q) { return ['sparkles', q]; });
    GENERIC_Q.forEach(function (g) { if (cards.length < 4 && !cards.some(function (c) { return c[1] === g[1]; })) cards.push(g); });
    var copy = !ready.length ? (state.docs.some(function (d) { return isBusyStatus(d.status); }) ? 'Your documents are being prepared. Questions work as soon as one is ready.' : 'Upload a document, then ask anything. Every answer cites the page it came from.') : 'Answers come only from your documents, with a citation for every claim.';
    var sig = copy + '|' + cards.map(function (c) { return c[1]; }).join('|') + '|' + (ready.length ? 1 : 0);
    if (w && w.dataset.sig === sig) return;
    if (!w) { w = document.createElement('div'); w.id = 'welcome'; w.className = 'welcome'; thread.appendChild(w); }
    w.dataset.sig = sig;
    w.innerHTML = '<div class="welcome-mark">' + LOGO + '</div><h1 class="welcome-title">Ask RagBot about your documents</h1><p class="welcome-copy">' + esc(copy) + '</p>' +
      '<div class="welcome-cards">' + cards.map(function (c) {
        return '<button type="button" class="wcard" data-q="' + esc(c[1]) + '">' + icon(c[0]) + '<span>' + esc(c[1]) + '</span></button>';
      }).join('') + '</div>';
    $$('.wcard', w).forEach(function (b) { b.addEventListener('click', function () { askQuestion(b.dataset.q); }); });
    icons();
  }

  /* ---------- turns ---------- */
  function looksLikeNotFound(txt) {
    var t = txt.trim();
    if (!t) return false;
    return t.length < 9 ? 'NOT_FOUND'.indexOf(t) === 0 : t.indexOf('NOT_FOUND') === 0;
  }

  function buildTurn(t) {
    var el = document.createElement('article');
    el.className = 'turn';
    el.innerHTML =
      '<div class="q"><div class="bubble-user"></div></div>' +
      '<div class="a"><span class="avatar" aria-hidden="true">' + LOGO + '</span><div class="a-col">' +
        '<div class="prog-top" hidden><span></span></div>' +
        '<div class="think" hidden></div>' +
        '<div class="a-body" aria-live="polite"></div>' +
        '<div class="src-row"></div><div class="a-actions"></div><div class="metrics"></div>' +
      '</div></div>';
    $('.bubble-user', el).textContent = t.q;
    $('#thread').appendChild(el);
    var rt = { t: t, el: el, body: $('.a-body', el), think: $('.think', el), prog: $('.prog-top', el), srcRow: $('.src-row', el), actions: $('.a-actions', el), metrics: $('.metrics', el), terms: queryTerms(t.q), steps: [], timer: 0 };
    state.rts[t.id] = rt;
    el.addEventListener('click', function (e) { turnClick(rt, e); });
    return rt;
  }

  function turnClick(rt, e) {
    var c = e.target.closest('.cite[data-n]');
    if (c) return citeClick(rt, +c.dataset.n);
    var sc = e.target.closest('.scard[data-n]');
    if (sc) return citeClick(rt, +sc.dataset.n);
    var ts = e.target.closest('.think-sum');
    if (ts) { var th = rt.think; th.classList.toggle('is-open'); ts.setAttribute('aria-expanded', th.classList.contains('is-open') ? 'true' : 'false'); return; }
    var mt = e.target.closest('.mtog');
    if (mt) { var bd = $('.breakdown', rt.metrics); bd.hidden = !bd.hidden; mt.setAttribute('aria-expanded', bd.hidden ? 'false' : 'true'); return; }
    var act = e.target.closest('[data-act]');
    if (!act) return;
    var a = act.dataset.act, t = rt.t;
    if (a === 'copy') {
      copyText(t.answer || '').then(function () {
        act.classList.add('on'); act.innerHTML = icon('check', 'pop') + '<span>Copied</span>'; icons();
        setTimeout(function () { act.classList.remove('on'); act.innerHTML = icon('copy') + '<span>Copy</span>'; icons(); }, 1600);
      }).catch(function () { toast('Could not copy to clipboard', 'err'); });
    } else if (a === 'regen') {
      if (!state.busy) regenerate(rt);
    } else if (a === 'up' || a === 'down') {
      t.fb = t.fb === a ? null : a; saveConvs();
      $$('[data-act="up"],[data-act="down"]', rt.actions).forEach(function (b) { b.classList.toggle('on', t.fb === b.dataset.act); b.setAttribute('aria-pressed', t.fb === b.dataset.act ? 'true' : 'false'); });
      if (t.fb) toast('Thanks for the feedback');
    } else if (a === 'sources') {
      var hidden = rt.srcRow.hidden = !rt.srcRow.hidden;
      act.classList.toggle('on', !hidden); act.setAttribute('aria-pressed', hidden ? 'false' : 'true');
      if (!hidden) { openSources(); renderSources(rt, null); }
    }
  }

  function refreshActions() {
    var turns = state.cur ? state.cur.turns : [];
    var last = turns.length ? turns[turns.length - 1].id : -1;
    Object.keys(state.rts).forEach(function (id) {
      var b = $('[data-act="regen"]', state.rts[id].actions);
      if (b) b.hidden = +id !== last;
    });
  }

  function regenerate(rt) {
    var cur = state.cur;
    if (!cur) return;
    var idx = cur.turns.indexOf(rt.t);
    if (idx !== cur.turns.length - 1) return;
    var q = rt.t.q;
    cur.turns.pop();
    clearInterval(rt.timer); delete state.rts[rt.t.id]; rt.el.remove();
    askQuestion(q);
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    return new Promise(function (resolve, reject) {
      var ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy') ? resolve() : reject(new Error('copy failed')); } catch (e) { reject(e); }
      ta.remove();
    });
  }

  /* thinking steps */
  function renderSteps(rt, live) {
    var th = rt.think;
    var steps = rt.steps;
    if (!steps.length) { th.hidden = true; return; }
    th.hidden = false;
    var cur = live ? steps.length - 1 : -1;
    var list = steps.map(function (s, i) {
      var isCur = i === cur;
      return '<li class="step' + (isCur ? ' is-current' : '') + '"><span class="s-ico">' + (isCur ? '<span class="spin"></span>' : icon('check')) + '</span><span>' + esc(s.label) + '</span><span class="s-time">' + (isCur ? '' : (has(s.dur) ? fmtMs(s.dur) : '')) + '</span></li>';
    }).join('');
    var sum = '';
    if (!live) {
      var ms = retrievalMs(rt.t);
      var n = rt.t.sources.length;
      sum = '<button type="button" class="think-sum" aria-expanded="false">' + icon('chevron-down', 'chev') + '<span>' + (n ? 'Searched <span class="mono">' + n + '</span> passage' + (n === 1 ? '' : 's') + (ms ? ' in <span class="mono">' + fmtMs(ms) + '</span>' : '') : 'Searched your documents' + (ms ? ' in <span class="mono">' + fmtMs(ms) + '</span>' : '')) + '</span></button>';
    }
    th.className = 'think' + (live ? '' : ' is-collapsed');
    th.innerHTML = sum + '<ul class="steps">' + list + '</ul>';
    icons();
  }
  function retrievalMs(t) {
    if (t.metrics && has(t.metrics.retrieval_ms)) return t.metrics.retrieval_ms;
    if (t.latency && has(t.latency.retrieval)) return t.latency.retrieval;
    return 0;
  }
  function clockNow(rt) { return performance.now() - rt.t0 + (rt.off || 0); }
  function startStep(rt, stage, label, startMs) {
    var last = rt.steps[rt.steps.length - 1];
    if (last && last.stage === stage) { last.label = label || last.label; return; }
    if (last) last.dur = Math.max(0, startMs - last.start);
    rt.steps.push({ stage: stage, label: label || stage, start: startMs });
  }
  function closeSteps(rt) {
    var last = rt.steps[rt.steps.length - 1];
    if (last && !has(last.dur)) last.dur = Math.max(0, clockNow(rt) - last.start);
  }

  function metricsHTML(t) {
    var m = t.metrics, lat = t.latency;
    if (!m && !lat) return '';
    m = m || {};
    var ret = has(m.retrieval_ms) ? m.retrieval_ms : (lat ? lat.retrieval : null);
    var llm = has(m.llm_ms) ? m.llm_ms : (lat ? lat.llm : null);
    var total = has(m.total_ms) ? m.total_ms : (has(ret) && has(llm) ? ret + llm : null);
    var est = m.estimated_tokens ? ' <span class="est">est.</span>' : '';
    var parts = [];
    if (has(m.ttft_ms)) parts.push('<span class="m" data-tip="Time to first token">' + icon('zap') + 'TTFT <b>' + fmtMs(m.ttft_ms) + '</b></span>');
    if (has(total)) parts.push('<span class="m" data-tip="Total time">' + icon('clock') + '<b>' + fmtMs(total) + '</b></span>');
    if (has(m.prompt_tokens)) parts.push('<span class="m" data-tip="Tokens in">' + icon('arrow-down-to-line') + '<b>' + fmtInt(m.prompt_tokens) + '</b> in' + est + '</span>');
    if (has(m.completion_tokens)) parts.push('<span class="m" data-tip="Tokens out">' + icon('arrow-up-from-line') + '<b>' + fmtInt(m.completion_tokens) + '</b> out' + est + '</span>');
    if (has(m.tokens_per_sec)) parts.push('<span class="m" data-tip="Tokens per second">' + icon('gauge') + '<b>' + Number(m.tokens_per_sec).toFixed(1) + '</b> tok/s</span>');
    if (m.model) parts.push('<span class="m model" data-tip="Model">' + icon('cpu') + '<b>' + esc(m.model) + '</b></span>');
    if (m.cache_hit || m.cached_tokens > 0) parts.push('<span class="cache-badge" data-tip="Prompt served from cache">' + icon('database') + 'Cache hit' + (m.cached_tokens > 0 ? ' ' + fmtInt(m.cached_tokens) : '') + '</span>');
    var bd = '';
    if (has(ret) && has(llm) && ret + llm > 0) {
      var tot = ret + llm, rp = Math.round((ret / tot) * 100);
      parts.push('<button type="button" class="mtog" aria-expanded="false">Timing' + icon('chevron-down', 'chev') + '</button>');
      bd = '<div class="breakdown" hidden><div class="bd-bar"><span style="width:' + rp + '%;background:var(--c-mid)"></span><span style="width:' + (100 - rp) + '%;background:var(--accent)"></span></div>' +
        '<div class="bd-leg"><span><i style="background:var(--c-mid)"></i>Retrieval ' + fmtMs(ret) + '</span><span><i style="background:var(--accent)"></i>Generation ' + fmtMs(llm) + '</span></div></div>';
    }
    return parts.join('') + bd;
  }

  function actionsHTML(t) {
    var h = '';
    if (t.answer && t.answer.trim() && !t.error) h += '<button type="button" class="btn small ghost" data-act="copy">' + icon('copy') + '<span>Copy</span></button>';
    h += '<button type="button" class="btn small ghost" data-act="regen" data-tip="Regenerate answer">' + icon('refresh-cw') + '<span>Retry</span></button>';
    if (t.answer && !t.error && t.found !== false) {
      h += '<button type="button" class="btn small ghost iconly' + (t.fb === 'up' ? ' on' : '') + '" data-act="up" aria-label="Good answer" aria-pressed="' + (t.fb === 'up') + '" data-tip="Good answer">' + icon('thumbs-up') + '</button>';
      h += '<button type="button" class="btn small ghost iconly' + (t.fb === 'down' ? ' on' : '') + '" data-act="down" aria-label="Poor answer" aria-pressed="' + (t.fb === 'down') + '" data-tip="Poor answer">' + icon('thumbs-down') + '</button>';
    }
    if (t.sources && t.sources.length) h += '<button type="button" class="btn small ghost on" data-act="sources" aria-pressed="true">' + icon('quote') + '<span>Sources (' + t.sources.length + ')</span></button>';
    return h;
  }

  function srcRowHTML(t) {
    var mx = Math.max.apply(null, (t.sources || []).map(function (s) { return s.score || 0; }).concat([0.0001]));
    return (t.sources || []).map(function (s) {
      var rel = clamp01((s.score || 0) / mx);
      return '<button type="button" class="scard" title="Relevance of this passage compared with the best match" data-n="' + s.n + '" aria-label="Open source ' + s.n + ', ' + esc(s.filename) + ' page ' + esc(s.page) + '">' +
        '<div class="sc-top"><span class="sc-n">' + s.n + '</span><span class="sc-file" title="' + esc(s.filename) + '">' + esc(s.filename) + '</span></div>' +
        '<div class="sc-bot"><span>p.' + esc(s.page) + '</span><div class="bar"><span style="width:' + Math.round(rel * 100) + '%"></span></div><span>' + Math.round(rel * 100) + '%</span></div></button>';
    }).join('');
  }

  /* final render of a turn from its data (used for live finish and stored chats) */
  function paintFinal(rt) {
    var t = rt.t;
    rt.prog.hidden = true;
    clearInterval(rt.timer);
    rt.body.setAttribute('aria-busy', 'false');
    if (!rt.steps.length && t.steps && t.steps.length) rt.steps = t.steps.map(function (s) { return { label: s.label, dur: s.dur }; });
    renderSteps(rt, false);
    if (t.error) {
      rt.body.innerHTML = '<div class="card err" role="alert"><div class="card-head">' + icon('triangle-alert') + '<span>Could not answer</span></div><p>' + esc(t.error) + '</p></div>' +
        (t.answer && t.answer.trim() ? '<div style="margin-top:12px">' + renderMarkdown(t.answer, t.sources.length) + '</div>' : '');
    } else if (t.found === false) {
      var hints = (t.sources || []).slice(0, 3);
      rt.body.innerHTML = '<div class="card nf"><div class="card-head">' + icon('search-x') + '<span>Not found in your documents</span></div>' +
        '<p>The documents do not appear to answer this. Try rephrasing, or check that the right documents are selected.</p>' +
        (hints.length ? '<div class="hints-label">Closest passages</div><div class="hints">' + hints.map(function (s) {
          return '<button type="button" class="hint scard-hint" data-n="' + s.n + '"><div class="h-top">' + icon('file-text') + '<span>' + esc(s.filename) + '</span><span class="mono">p.' + esc(s.page) + '</span></div><div class="h-text">' + esc(s.text) + '</div></button>';
        }).join('') + '</div>' : '') + '</div>';
      $$('.hint', rt.body).forEach(function (b) { b.addEventListener('click', function () { citeClick(rt, +b.dataset.n); }); });
    } else if (t.answer && t.answer.trim()) {
      rt.body.innerHTML = renderMarkdown(t.answer, t.sources.length) + (t.stopped ? '<p class="stopped">Stopped</p>' : '');
    } else {
      rt.body.innerHTML = t.stopped ? '<p class="stopped">Stopped</p>' : '<div class="card err" role="alert"><div class="card-head">' + icon('triangle-alert') + '<span>No response</span></div><p>The server closed the connection before answering. Please try again.</p></div>';
    }
    var showCards = t.found !== false && t.sources && t.sources.length;
    rt.srcRow.innerHTML = showCards ? srcRowHTML(t) : '';
    rt.srcRow.hidden = false;
    rt.actions.innerHTML = actionsHTML(t);
    rt.metrics.innerHTML = metricsHTML(t);
    rt.el.classList.add('is-done');
    icons();
    refreshActions();
  }

  /* ---------- asking ---------- */
  function buildHistory() {
    var out = [];
    if (!state.cur) return out;
    state.cur.turns.forEach(function (t) {
      if (t.error || (!t.answer && t.found !== false)) return;
      out.push({ role: 'user', content: t.q });
      out.push({ role: 'assistant', content: t.found === false ? 'I could not find the answer in the documents.' : t.answer });
    });
    return out.slice(-6);
  }

  function scrollDown(force) {
    var w = $('#thread-wrap');
    if (force || state.stick) { w.scrollTop = w.scrollHeight; }
  }

  function updateSendState() {
    var input = $('#composer-input'), send = $('#send');
    var hasText = input.value.trim().length > 0;
    send.disabled = state.busy ? false : !hasText;
    send.classList.toggle('is-busy', state.busy);
    send.setAttribute('aria-label', state.busy ? 'Stop generating' : 'Send question');
  }
  function autosize() {
    var t = $('#composer-input');
    t.style.height = 'auto';
    t.style.height = Math.min(t.scrollHeight, 180) + 'px';
  }

  function askQuestion(q) {
    q = (q || '').trim();
    if (!q || state.busy) return;
    if (state.view !== 'chat') setView('chat');
    if (isNarrow()) toggleSidebar(false);
    var ready = readyDocs(), ids = includedIds();
    // One chat, any number of documents: never block on selection, fall back to every ready document.
    if (ready.length && !ids.length) { state.excluded.clear(); saveExcluded(); renderDocs(); ids = includedIds(); }

    var history = buildHistory();
    if (!state.cur) {
      state.cur = { id: 'c' + Date.now().toString(36) + Math.random().toString(36).slice(2, 5), title: makeTitle(q), created: Date.now(), updated: Date.now(), turns: [] };
      state.convs.unshift(state.cur);
    }
    var w = $('#welcome'); if (w) w.remove();
    var t = { id: ++state.seq + Date.now(), q: q, answer: '', found: null, sources: [], metrics: null, latency: null, error: null, stopped: false, steps: [], fb: null };
    state.cur.turns.push(t);
    state.cur.updated = Date.now();
    sortConvs();
    var rt = buildTurn(t);
    rt.t0 = performance.now(); rt.off = 0;
    rt.prog.hidden = false;
    rt.body.setAttribute('aria-busy', 'true');
    rt.steps.push({ stage: 'sending', label: 'Sending question', start: 0 });
    renderSteps(rt, true);
    rt.timer = setInterval(function () {
      var cur = $('.step.is-current .s-time', rt.think);
      var s = rt.steps[rt.steps.length - 1];
      if (cur && s) cur.textContent = fmtMs(clockNow(rt) - s.start);
    }, 100);
    refreshActions();
    renderHistory();
    state.stick = true;
    scrollDown(true);

    var input = $('#composer-input');
    input.value = ''; autosize();
    state.busy = true; updateSendState();
    var ctrl = new AbortController();
    state.abort = ctrl;

    var raw = '', collapsed = false, doneEvt = null, errMsg = null, raf = 0;

    function collapseThink() {
      if (collapsed) return; collapsed = true;
      closeSteps(rt);
      clearInterval(rt.timer);
      t.steps = rt.steps.map(function (s) { return { label: s.label, dur: s.dur }; });
      // temporary summary based on live data
      t.latency = t.latency || { retrieval: Math.round(retrievalLive(rt)), llm: 0 };
      renderSteps(rt, false);
    }
    function retrievalLive(r) {
      var g = r.steps.filter(function (s) { return s.stage === 'generating'; })[0];
      return g ? g.start : clockNow(r);
    }
    function paint() {
      raf = 0;
      if (looksLikeNotFound(raw)) return;
      rt.body.innerHTML = renderMarkdown(raw, t.sources.length) + '<span class="caret" aria-hidden="true"></span>';
      scrollDown(false);
    }

    function onEvent(ev, data) {
      data = data || {};
      if (ev === 'status') {
        var el = has(data.elapsed_ms) ? Number(data.elapsed_ms) : clockNow(rt);
        rt.off = el - (performance.now() - rt.t0);
        if (!collapsed) { startStep(rt, data.stage || 'working', data.label || data.stage, el); renderSteps(rt, true); }
      } else if (ev === 'sources') {
        t.sources = data.sources || [];
        rt.srcRow.innerHTML = srcRowHTML(t);
        renderSources(rt, null);
      } else if (ev === 'token') {
        raw += data.text || '';
        if (!collapsed && !looksLikeNotFound(raw)) collapseThink();
        if (!raf) raf = requestAnimationFrame(paint);
      } else if (ev === 'done') { doneEvt = data; }
      else if (ev === 'error') { errMsg = data.message || 'Something went wrong'; }
    }

    function parseFrame(frame) {
      var ev = 'message', dl = [];
      frame.split('\n').forEach(function (line) {
        if (!line || line.charAt(0) === ':') return;
        var i = line.indexOf(':');
        var field = i < 0 ? line : line.slice(0, i), val = i < 0 ? '' : line.slice(i + 1);
        if (val.charAt(0) === ' ') val = val.slice(1);
        if (field === 'event') ev = val; else if (field === 'data') dl.push(val);
      });
      if (!dl.length) return;
      var parsed = null;
      try { parsed = JSON.parse(dl.join('\n')); } catch (e) { return; }
      onEvent(ev, parsed);
    }

    fetch('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
      body: JSON.stringify({ question: q, doc_ids: ids, history: history, model: activeModel() || null }),
      signal: ctrl.signal
    }).then(function (res) {
      if (!res.ok) {
        return res.text().then(function (tx) {
          var m = 'Request failed (' + res.status + ')';
          try { var j = JSON.parse(tx); if (j.detail) m = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail); } catch (e) { /* ignore */ }
          throw new Error(m);
        });
      }
      var reader = res.body.getReader(), dec = new TextDecoder('utf-8'), buf = '';
      function pump() {
        return reader.read().then(function (r) {
          if (r.done) {
            buf = (buf + dec.decode()).replace(/\r\n?/g, '\n');
            if (buf.trim()) parseFrame(buf);
            return;
          }
          buf = (buf + dec.decode(r.value, { stream: true })).replace(/\r\n?/g, '\n');
          var idx;
          while ((idx = buf.indexOf('\n\n')) >= 0) { var f = buf.slice(0, idx); buf = buf.slice(idx + 2); parseFrame(f); }
          return pump();
        });
      }
      return pump();
    }).then(function () { finish(false); }).catch(function (e) {
      if (e && e.name === 'AbortError') finish(true);
      else { errMsg = errMsg || (e && e.message) || 'Network error'; finish(false); }
    });

    function finish(aborted) {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      state.busy = false; state.abort = null;
      closeSteps(rt);
      t.steps = rt.steps.map(function (s) { return { label: s.label, dur: s.dur }; });
      if (doneEvt) {
        t.found = doneEvt.found !== false;
        t.answer = doneEvt.answer || raw;
        t.metrics = doneEvt.metrics || null;
        t.latency = doneEvt.latency_ms || null;
        if (t.found === false) t.answer = '';
      } else {
        t.answer = looksLikeNotFound(raw) ? '' : raw;
        t.latency = null;
      }
      if (aborted) t.stopped = true;
      if (errMsg && !aborted) { t.error = errMsg; if (/key|configur/i.test(errMsg)) loadConfig(); }
      if (!doneEvt && !errMsg && !aborted && !raw.trim()) t.error = null;
      state.cur && (state.cur.updated = Date.now());
      saveConvs();
      paintFinal(rt);
      if (t.sources.length) renderSources(rt, null);
      updateSendState();
      scrollDown(false);
      if (!aborted) $('#composer-input').focus({ preventScroll: true });
    }
  }

  function setupChat() {
    var input = $('#composer-input');
    input.addEventListener('input', function () { autosize(); updateSendState(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); if (!state.busy) askQuestion(input.value); }
    });
    $('#composer').addEventListener('submit', function (e) {
      e.preventDefault();
      if (state.busy) { if (state.abort) state.abort.abort(); return; }
      askQuestion(input.value);
    });
    $('#send').addEventListener('pointerdown', function (e) {
      var b = e.currentTarget, r = document.createElement('span');
      r.className = 'ripple'; var rc = b.getBoundingClientRect();
      r.style.left = (e.clientX - rc.left) + 'px'; r.style.top = (e.clientY - rc.top) + 'px';
      b.appendChild(r); setTimeout(function () { r.remove(); }, 600);
    });
    $('#btn-new').addEventListener('click', newChat);
    var wrap = $('#thread-wrap'), tb = $('#to-bottom');
    wrap.addEventListener('scroll', function () {
      var near = wrap.scrollHeight - wrap.scrollTop - wrap.clientHeight < 80;
      state.stick = near; tb.hidden = near;
    }, { passive: true });
    tb.addEventListener('click', function () { state.stick = true; wrap.scrollTo({ top: wrap.scrollHeight, behavior: 'smooth' }); });
    $('#hist-search').addEventListener('input', debounce(renderHistory, 150));
    $('#docs-toggle').addEventListener('click', function () {
      var sec = $('#docs-sec'), c = sec.classList.toggle('is-collapsed');
      $('#docs-toggle').setAttribute('aria-expanded', c ? 'false' : 'true');
    });
  }

  /* ---------- voice input ---------- */
  var voice = { rec: null, on: false, cancelled: false, errored: false, base: '', text: '' };
  function setupVoice() {
    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    var btn = $('#btn-mic'), input = $('#composer-input'), auto = $('#auto-send');
    var saved = store('ragbot.autosend');
    auto.checked = saved === null ? true : saved === '1';
    auto.addEventListener('change', function () { store('ragbot.autosend', auto.checked ? '1' : '0'); });
    if (!SR) {
      btn.classList.add('is-unsupported');
      btn.setAttribute('aria-label', 'Voice input is not supported in this browser');
      btn.dataset.tip = 'Voice input needs Chrome or Edge';
      $('#auto-send-wrap').hidden = true;
      btn.addEventListener('click', function () { toast('Voice input is not supported in this browser. Try Chrome or Edge.', 'err'); });
      return;
    }
    function ui(on) {
      voice.on = on;
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.setAttribute('aria-label', on ? 'Stop voice input' : 'Start voice input');
      $('#composer').classList.toggle('is-listening', on);
      input.placeholder = on ? 'Listening...' : 'Ask anything about your documents';
    }
    function start() {
      if (voice.on || state.view !== 'chat') return;
      var rec = new SR();
      rec.continuous = false; rec.interimResults = true; rec.lang = navigator.language || 'en-US';
      voice.rec = rec; voice.cancelled = false; voice.errored = false; voice.text = '';
      voice.base = input.value ? input.value.replace(/\s*$/, ' ') : '';
      rec.onresult = function (e) {
        var f = '', i = '';
        for (var k = 0; k < e.results.length; k++) { if (e.results[k].isFinal) f += e.results[k][0].transcript; else i += e.results[k][0].transcript; }
        voice.text = (f + i).trim();
        input.value = voice.base + f + i;
        autosize(); updateSendState();
      };
      rec.onerror = function (e) {
        voice.errored = true;
        var m = {
          'not-allowed': 'Microphone access is blocked. Allow the microphone in your browser address bar, then try again.',
          'service-not-allowed': 'Microphone access is blocked. Allow the microphone in your browser address bar, then try again.',
          'no-speech': 'No speech heard. Click the mic and try again.',
          'network': 'The speech service could not be reached. Voice input needs an internet connection.',
          'audio-capture': 'No microphone was found.'
        }[e.error];
        if (m) toast(m, 'err');
        else if (e.error !== 'aborted') toast('Voice input failed (' + e.error + ').', 'err');
      };
      rec.onend = function () {
        ui(false); voice.rec = null;
        if (voice.cancelled) { input.value = voice.base.replace(/\s+$/, ''); autosize(); updateSendState(); return; }
        if (!voice.errored && voice.text && auto.checked && !state.busy) askQuestion(input.value);
      };
      try { rec.start(); ui(true); } catch (err) { toast('Could not start voice input.', 'err'); ui(false); }
    }
    function stop() { if (voice.rec) { try { voice.rec.stop(); } catch (e) { /* ignore */ } } }
    function cancel() { if (voice.rec) { voice.cancelled = true; try { voice.rec.abort(); } catch (e) { /* ignore */ } } }
    btn.addEventListener('click', function () { voice.on ? stop() : start(); });
    document.addEventListener('keydown', function (e) {
      if (e.ctrlKey && e.shiftKey && (e.key === 'M' || e.key === 'm')) { e.preventDefault(); voice.on ? stop() : start(); }
      else if (e.key === 'Escape' && voice.on) { e.preventDefault(); cancel(); }
    });
  }

  /* ---------- command palette ---------- */
  function openPalette() {
    if ($('#palette')) return;
    var prev = document.activeElement;
    var ov = document.createElement('div');
    ov.className = 'palette-ov'; ov.id = 'palette';
    ov.innerHTML = '<div class="palette" role="dialog" aria-modal="true" aria-label="Quick actions">' +
      '<div class="pal-in">' + icon('search') + '<input id="pal-input" type="text" placeholder="Search chats and documents, or run an action" autocomplete="off" aria-label="Search"><kbd>Esc</kbd></div>' +
      '<ul class="pal-list" id="pal-list" role="listbox"></ul>' +
      '<div class="pal-foot"><span><kbd>Up</kbd><kbd>Down</kbd> navigate</span><span><kbd>Enter</kbd> select</span></div></div>';
    document.body.appendChild(ov);
    var input = $('#pal-input', ov), list = $('#pal-list', ov), sel = 0, items = [];
    function build() {
      var term = input.value.trim().toLowerCase();
      var all = [
        { g: 'Actions', i: 'square-pen', l: 'New chat', run: newChat },
        { g: 'Actions', i: 'cloud-upload', l: 'Upload documents', run: function () { $('#file-input').click(); } },
        { g: 'Actions', i: state.view === 'chat' ? 'chart-column' : 'message-square', l: state.view === 'chat' ? 'Open analytics' : 'Back to chat', run: function () { setView(state.view === 'chat' ? 'analytics' : 'chat'); } },
        { g: 'Actions', i: 'panel-left', l: 'Toggle sidebar', run: function () { toggleSidebar(); } }
      ];
      state.convs.forEach(function (c) { all.push({ g: 'Chats', i: 'message-square', l: c.title, run: function () { openConv(c.id); } }); });
      state.docs.forEach(function (d) { all.push({ g: 'Documents', i: 'file-text', l: d.filename, run: function () { toggleSidebar(true); openDocsSection(); state.open = d.id; updateOpen(); var li = docEls[d.id]; if (li) li.scrollIntoView({ block: 'nearest' }); } }); });
      items = all.filter(function (x) { return !term || x.l.toLowerCase().indexOf(term) >= 0; }).slice(0, 30);
      sel = Math.min(sel, Math.max(0, items.length - 1));
      var g = '', h = '';
      items.forEach(function (x, idx) {
        if (x.g !== g) { g = x.g; h += '<li class="pal-group" role="presentation">' + g + '</li>'; }
        h += '<li class="pal-item' + (idx === sel ? ' is-sel' : '') + '" role="option" data-i="' + idx + '" aria-selected="' + (idx === sel) + '">' + icon(x.i) + '<span>' + esc(x.l) + '</span></li>';
      });
      list.innerHTML = h || '<li class="pal-none">No matches</li>';
      icons();
      var s = $('.is-sel', list); if (s) s.scrollIntoView({ block: 'nearest' });
    }
    function close() { ov.remove(); if (prev && prev.focus) prev.focus(); }
    function run(idx) { var it = items[idx]; if (!it) return; close(); it.run(); }
    input.addEventListener('input', function () { sel = 0; build(); });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); build(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); build(); }
      else if (e.key === 'Enter') { e.preventDefault(); run(sel); }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
    });
    list.addEventListener('click', function (e) { var li = e.target.closest('.pal-item'); if (li) run(+li.dataset.i); });
    list.addEventListener('mousemove', function (e) { var li = e.target.closest('.pal-item'); if (li && +li.dataset.i !== sel) { sel = +li.dataset.i; $$('.pal-item', list).forEach(function (n) { n.classList.toggle('is-sel', +n.dataset.i === sel); }); } });
    ov.addEventListener('mousedown', function (e) { if (e.target === ov) close(); });
    build(); input.focus();
  }

  /* ---------- analytics ---------- */
  function niceMax(v) {
    if (v <= 4) return 4;
    var p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 4 ? 4 : n <= 5 ? 5 : 10) * p;
  }
  function barChart(items, opts) {
    var W = opts.w, H = opts.h, padL = 28, padB = 20, padT = 8, padR = 4;
    var max = niceMax(Math.max.apply(null, items.map(function (i) { return i.v; }).concat([0])));
    var iw = W - padL - padR, ih = H - padT - padB;
    var slot = iw / items.length, bw = Math.max(3, slot * (opts.fill || 0.62));
    var s = '<svg class="chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(opts.label) + '">';
    for (var g = 0; g <= 4; g++) {
      var y = padT + ih - (ih * g) / 4;
      s += '<line class="grid-line" x1="' + padL + '" x2="' + (W - padR) + '" y1="' + y + '" y2="' + y + '"/><text x="' + (padL - 6) + '" y="' + (y + 3) + '" text-anchor="end">' + Math.round((max * g) / 4) + '</text>';
    }
    items.forEach(function (it, i) {
      var h = it.v > 0 ? Math.max(2, (it.v / max) * ih) : 0;
      var x = padL + i * slot + (slot - bw) / 2, y2 = padT + ih - h;
      if (it.v > 0) s += '<rect class="bar-rect" data-tip="' + esc(it.tip) + '" x="' + x.toFixed(1) + '" y="' + y2.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="3" fill="' + (it.color || 'var(--accent)') + '"/>';
      else s += '<rect data-tip="' + esc(it.tip) + '" x="' + x.toFixed(1) + '" y="' + (padT + ih - 1.5) + '" width="' + bw.toFixed(1) + '" height="1.5" rx="1" fill="var(--line)"/>';
      if (it.label) s += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 5) + '" text-anchor="middle">' + esc(it.label) + '</text>';
    });
    return s + '</svg>';
  }
  function donut(answered, notFound) {
    var total = answered + notFound, R = 54, C = 2 * Math.PI * R;
    var s = '<svg class="donut" viewBox="0 0 132 132" role="img" aria-label="' + answered + ' answered, ' + notFound + ' not found"><circle cx="66" cy="66" r="' + R + '" fill="none" stroke="var(--track)" stroke-width="14"/>';
    if (total > 0) {
      var a = (answered / total) * C, n = (notFound / total) * C, gap = answered > 0 && notFound > 0 ? 3 : 0;
      if (answered > 0) s += '<circle data-tip="Answered: ' + answered + '" cx="66" cy="66" r="' + R + '" fill="none" stroke="var(--accent)" stroke-width="14" stroke-dasharray="' + Math.max(0, a - gap) + ' ' + C + '" transform="rotate(-90 66 66)"/>';
      if (notFound > 0) s += '<circle data-tip="Not found: ' + notFound + '" cx="66" cy="66" r="' + R + '" fill="none" stroke="var(--amber)" stroke-width="14" stroke-dasharray="' + Math.max(0, n - gap) + ' ' + C + '" stroke-dashoffset="' + (-a) + '" transform="rotate(-90 66 66)"/>';
    }
    return s + '<text class="d-num" x="66" y="68" text-anchor="middle">' + (total > 0 ? Math.round((answered / total) * 100) + '%' : '0%') + '</text><text class="d-lab" x="66" y="82" text-anchor="middle">answered</text></svg>';
  }
  function emptyBox(msg) { return '<div class="chart-empty"><span>' + esc(msg) + '</span></div>'; }

  function fmtKind(kind, v) {
    if (kind === 'pct') return Math.round(v * 100) + '<small>%</small>';
    if (kind === 'ms') return v >= 1000 ? (v / 1000).toFixed(1) + '<small> s</small>' : Math.round(v) + '<small> ms</small>';
    if (kind === 'f1') return Number(v).toFixed(1);
    return fmtInt(Math.round(v));
  }
  function animateCounters(root) {
    $$('.t-val[data-v]', root).forEach(function (el) {
      var to = parseFloat(el.dataset.v), kind = el.dataset.kind, key = el.dataset.key;
      var from = has(state.anPrev[key]) ? state.anPrev[key] : 0;
      state.anPrev[key] = to;
      if (from === to || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { el.innerHTML = fmtKind(kind, to); return; }
      var t0 = performance.now(), dur = 700;
      (function step(now) {
        var p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
        el.innerHTML = fmtKind(kind, from + (to - from) * e);
        if (p < 1) requestAnimationFrame(step);
      })(t0);
    });
  }

  function renderAnalytics(a) {
    var t = a.totals || {}, q = t.questions || 0;
    function tile(ic, label, key, v, kind, sub, show) {
      return '<div class="tile"><div class="t-label">' + icon(ic) + '<span>' + label + '</span></div>' +
        (show === false ? '<div class="t-val">-</div>' : '<div class="t-val" data-v="' + (Number(v) || 0) + '" data-kind="' + kind + '" data-key="' + key + '">' + fmtKind(kind, Number(v) || 0) + '</div>') +
        (sub ? '<div class="t-sub">' + esc(sub) + '</div>' : '') + '</div>';
    }
    var tin = a.total_prompt_tokens || 0, tout = a.total_completion_tokens || 0, tcache = a.total_cached_tokens || 0;
    var h = '<div class="an-top"><div class="an-head"><h1>Analytics</h1><p>How your documents are used and how fast answers arrive.</p></div>' +
      '<div class="reset-wrap" id="reset-wrap"><button type="button" class="btn small" id="reset-btn">' + icon('rotate-ccw') + '<span>Reset analytics</span></button></div></div>';
    h += '<div class="tiles">' +
      tile('files', 'Documents', 'docs', t.documents, 'int') +
      tile('book-open', 'Pages', 'pages', t.pages, 'int', fmtInt(t.words) + ' words') +
      tile('layers', 'Chunks', 'chunks', t.chunks, 'int') +
      tile('message-circle', 'Questions', 'q', q, 'int', a.errors ? fmtInt(a.errors) + ' errors' : '') +
      tile('badge-check', 'Answer rate', 'rate', a.answer_rate, 'pct', q ? fmtInt(a.answered) + ' answered' : 'No data yet', q > 0) +
      tile('timer', 'Avg latency', 'lat', a.avg_latency_ms, 'ms', q ? fmtMs(a.avg_retrieval_ms) + ' retrieval' : 'No data yet', q > 0) +
      tile('zap', 'Avg TTFT', 'ttft', a.avg_ttft_ms, 'ms', '', q > 0 && has(a.avg_ttft_ms)) +
      tile('clock', 'P95 total', 'p95', a.p95_total_ms, 'ms', '', q > 0 && has(a.p95_total_ms)) +
      tile('database', 'Cache hit rate', 'cache', a.cache_hit_rate, 'pct', tcache ? fmtInt(tcache) + ' cached tokens' : '', q > 0 && has(a.cache_hit_rate)) +
      tile('gauge', 'Avg tokens/s', 'tps', a.avg_tokens_per_sec, 'f1', '', q > 0 && has(a.avg_tokens_per_sec)) +
      tile('triangle-alert', 'Errors', 'err', a.errors, 'int') +
      tile('arrow-up-from-line', 'Tokens out', 'tout', tout, 'int', fmtInt(tin) + ' in') + '</div>';

    h += '<div class="grid2">';
    var answered = a.answered || 0, nf = a.not_found || 0;
    h += '<section class="panel span5"><h3>Answered vs not found</h3><p class="p-sub">Share of questions your documents could answer</p>';
    if (answered + nf > 0) {
      h += '<div class="donut-wrap">' + donut(answered, nf) + '<div class="legend">' +
        '<div class="row"><span class="sw" style="background:var(--accent)"></span><span>Answered</span><span class="lv">' + fmtInt(answered) + '</span></div>' +
        '<div class="row"><span class="sw" style="background:var(--amber)"></span><span>Not found</span><span class="lv">' + fmtInt(nf) + '</span></div></div></div>';
    } else h += emptyBox('Ask a question to see how often answers are found.');
    h += '<div class="metrics-grid"><div><div class="m-v">' + (q ? (Number(a.avg_citations) || 0).toFixed(1) : '-') + '</div><div class="m-l">Avg citations</div></div>' +
      '<div><div class="m-v">' + (q ? fmtMs(a.avg_retrieval_ms) : '-') + '</div><div class="m-l">Avg retrieval</div></div>' +
      '<div><div class="m-v">' + (q ? fmtMs(a.avg_latency_ms) : '-') + '</div><div class="m-l">Avg total</div></div></div></section>';

    var tl = a.timeline || [], tlTotal = tl.reduce(function (s, x) { return s + (x.count || 0); }, 0);
    h += '<section class="panel span7"><h3>Questions, last 24 hours</h3><p class="p-sub">Hourly volume, oldest on the left</p>';
    if (tl.length && tlTotal > 0) {
      h += barChart(tl.map(function (x, i) {
        var d = new Date(x.t), hr = isNaN(d) ? '' : d.getHours();
        return { v: x.count || 0, label: i % 4 === 0 && hr !== '' ? (hr < 10 ? '0' : '') + hr + ':00' : '', tip: (isNaN(d) ? '' : d.toLocaleString([], { hour: '2-digit', minute: '2-digit', month: 'short', day: 'numeric' }) + ': ') + (x.count || 0) + ' question' + (x.count === 1 ? '' : 's') };
      }), { w: 560, h: 190, label: 'Questions per hour over the last 24 hours' });
    } else h += emptyBox('No questions in the last 24 hours.');
    h += '</section>';

    var sb = a.score_buckets || [], sbTotal = sb.reduce(function (s, x) { return s + (x.count || 0); }, 0);
    h += '<section class="panel span5"><h3>Retrieval score distribution</h3><p class="p-sub">How strong the best passage was for each question</p>';
    if (sb.length && sbTotal > 0) {
      h += barChart(sb.map(function (x, i) { return { v: x.count || 0, label: x.label, color: ['var(--amber)', 'var(--c-amber2)', 'var(--c-mid)', 'var(--c-teal2)', 'var(--accent)'][Math.min(i, 4)], tip: x.label + ': ' + (x.count || 0) }; }), { w: 360, h: 190, fill: 0.56, label: 'Distribution of top retrieval score' });
    } else h += emptyBox('Scores appear once questions are asked.');
    h += '</section>';

    h += '<section class="panel span7"><h3>Tokens in vs out</h3><p class="p-sub">Prompt and completion volume across all answers</p>';
    if (tin + tout > 0) {
      var mx = Math.max(tin, tout, 1);
      h += '<div class="tok-row"><div class="u-line"><span>Tokens in</span><span class="v">' + fmtInt(tin) + (tcache ? ' (' + fmtInt(tcache) + ' cached)' : '') + '</span></div><div class="tok-bar"><span style="width:' + (tin / mx * 100) + '%;background:var(--c-mid)"></span><span style="width:' + (tcache / mx * 100) + '%;background:var(--accent)"></span></div></div>' +
        '<div class="tok-row"><div class="u-line"><span>Tokens out</span><span class="v">' + fmtInt(tout) + '</span></div><div class="tok-bar"><span style="width:' + (tout / mx * 100) + '%;background:var(--amber)"></span></div></div>';
    } else h += emptyBox('Token counts appear after the first answer.');
    h += '</section>';

    var bm = a.by_model || [];
    h += '<section class="panel span12"><h3>By model</h3><p class="p-sub">Speed per model that produced answers</p>';
    if (bm.length) {
      h += '<div class="table-wrap"><table class="tbl"><thead><tr><th>Model</th><th>Answers</th><th>Avg TTFT</th><th>Avg total</th></tr></thead><tbody>' + bm.map(function (m) {
        return '<tr><td class="num">' + esc(m.model) + '</td><td class="num">' + fmtInt(m.count) + '</td><td class="num">' + (has(m.avg_ttft_ms) ? fmtMs(m.avg_ttft_ms) : '-') + '</td><td class="num">' + (has(m.avg_total_ms) ? fmtMs(m.avg_total_ms) : '-') + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    } else h += emptyBox('No model data yet.');
    h += '</section>';

    var pd = (a.per_document || []).slice().sort(function (x, y) { return (y.questions || 0) - (x.questions || 0); });
    var maxQ = Math.max.apply(null, pd.map(function (x) { return x.questions || 0; }).concat([1]));
    h += '<section class="panel span12"><h3>Usage by document</h3><p class="p-sub">Questions whose retrieval touched each document</p>';
    if (pd.length) {
      h += '<div class="usage">' + pd.map(function (x) {
        return '<div class="usage-row"><div class="u-line"><span class="n" title="' + esc(x.filename) + '">' + esc(x.filename) + '</span><span class="v">' + fmtInt(x.questions) + ' q</span></div><div class="bar"><span style="width:' + Math.round(((x.questions || 0) / maxQ) * 100) + '%"></span></div><div class="u-sub">' + fmtInt(x.pages) + ' pages / ' + fmtInt(x.chunks) + ' chunks</div></div>';
      }).join('') + '</div>';
    } else h += emptyBox('Upload a document to track its usage.');
    h += '</section>';

    var rc = a.recent || [];
    h += '<section class="panel span12"><h3>Recent questions</h3><p class="p-sub">Latest 12, newest first</p>';
    if (rc.length) {
      h += '<div class="table-wrap"><table class="tbl"><thead><tr><th>Question</th><th>Result</th><th>TTFT</th><th>Total</th><th>Tokens in/out</th><th>Cache</th><th>Model</th><th>Top score</th><th>When</th></tr></thead><tbody>' + rc.map(function (r) {
        var total = has(r.total_ms) ? r.total_ms : r.latency_ms;
        return '<tr><td class="q-cell" title="' + esc(r.question) + '">' + esc(r.question) + '</td>' +
          '<td>' + (r.found ? '<span class="badge ok">Answered</span>' : '<span class="badge nf">Not found</span>') + '</td>' +
          '<td class="num">' + (has(r.ttft_ms) ? fmtMs(r.ttft_ms) : '-') + '</td><td class="num">' + (has(total) ? fmtMs(total) : '-') + '</td>' +
          '<td class="num">' + (has(r.prompt_tokens) || has(r.completion_tokens) ? fmtInt(r.prompt_tokens) + ' / ' + fmtInt(r.completion_tokens) : '-') + '</td>' +
          '<td>' + (r.cached ? '<span class="badge ok">Hit</span>' : '<span class="num">-</span>') + '</td>' +
          '<td class="num">' + (r.model ? esc(r.model) : '-') + '</td><td class="num">' + (Number(r.top_score) || 0).toFixed(2) + '</td><td class="when">' + esc(timeAgo(r.ts)) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    } else h += emptyBox('Your question history will show up here.');
    h += '</section></div>';

    var box = $('#an-inner');
    box.innerHTML = h;
    icons();
    animateCounters(box);
    var rb = $('#reset-btn');
    rb.addEventListener('click', function () {
      var wrap = $('#reset-wrap');
      wrap.innerHTML = '<span class="m-l">Erase all analytics?</span><button type="button" class="btn small danger" id="reset-yes">' + icon('trash-2') + '<span>Confirm</span></button><button type="button" class="btn small ghost" id="reset-no">Cancel</button>';
      icons();
      $('#reset-no').addEventListener('click', function () { loadAnalytics(false); });
      $('#reset-yes').addEventListener('click', function () {
        jfetch('/api/analytics', { method: 'DELETE' }).then(function () { state.anPrev = {}; toast('Analytics reset'); loadAnalytics(false); }).catch(function (e) { toast(e.message, 'err'); loadAnalytics(false); });
      });
      $('#reset-no').focus();
    });
  }

  function loadAnalytics(first) {
    var box = $('#an-inner');
    if (first && !box.dataset.loaded) {
      box.innerHTML = '<div class="an-top"><div class="an-head"><h1>Analytics</h1><p>How your documents are used and how fast answers arrive.</p></div></div><div class="an-skel"><div class="sk"></div><div class="sk"></div><div class="sk"></div><div class="sk"></div><div class="sk"></div><div class="sk"></div><div class="sk wide"></div><div class="sk wide"></div></div>';
    }
    return jfetch('/api/analytics').then(function (a) {
      if ($('#reset-yes') && !first) return;
      box.dataset.loaded = '1';
      renderAnalytics(a || {});
    }).catch(function (e) {
      if (!box.dataset.loaded) { box.innerHTML = '<div class="an-head"><h1>Analytics</h1></div><div class="card err" style="margin-top:20px"><div class="card-head">' + icon('triangle-alert') + '<span>Could not load analytics</span></div><p>' + esc(e.message) + '</p></div>'; icons(); }
    });
  }

  /* ---------- views and chrome ---------- */
  function moveIndicator() {
    var act = $('.tab.is-active'), ind = $('.tab-ind');
    if (!act || !ind) return;
    ind.style.width = act.offsetWidth + 'px';
    ind.style.transform = 'translateX(' + act.offsetLeft + 'px)';
  }
  function setView(v) {
    state.view = v;
    $$('.tab').forEach(function (t) {
      var on = t.dataset.view === v;
      t.classList.toggle('is-active', on);
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.tabIndex = on ? 0 : -1;
    });
    moveIndicator();
    $('#view-chat').hidden = v !== 'chat';
    $('#view-analytics').hidden = v !== 'analytics';
    $('#app').classList.toggle('is-analytics', v === 'analytics');
    $('#btn-sources').hidden = v !== 'chat';
    $('#btn-sidebar').hidden = v !== 'chat';
    clearInterval(state.anTimer); state.anTimer = null;
    if (v === 'analytics') {
      $('#app').classList.remove('sidebar-open', 'sources-open'); syncScrim();
      loadAnalytics(true);
      state.anTimer = setInterval(function () { if (state.view === 'analytics' && !document.hidden) loadAnalytics(false); }, 10000);
    }
  }

  function setupChrome() {
    $$('.tab').forEach(function (t) {
      t.addEventListener('click', function () { setView(t.dataset.view); });
      t.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
          var tabs = $$('.tab'), i = tabs.indexOf(t);
          var nx = tabs[(i + (e.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
          setView(nx.dataset.view); nx.focus();
        }
      });
    });
    $('#btn-sources').addEventListener('click', function () { sourcesVisible() ? closeSources() : openSources(); });
    $('#src-close').addEventListener('click', closeSources);
    $('#btn-sidebar').addEventListener('click', function () { toggleSidebar(); });
    $('#scrim').addEventListener('click', function () {
      $('#app').classList.remove('sidebar-open', 'sources-open');
      $('#btn-sidebar').setAttribute('aria-expanded', sidebarVisible() ? 'true' : 'false');
      $('#btn-sources').setAttribute('aria-expanded', sourcesVisible() ? 'true' : 'false');
      syncScrim();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !voice.on && !$('#palette') && !$('#scrim').hidden) $('#scrim').click();
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openPalette(); }
    });
    $('#banner-close').addEventListener('click', function () { $('#banner').hidden = true; store('ragbot.banner', '1'); });
    window.addEventListener('resize', function () {
      var app = $('#app');
      if (!isOverlay()) app.classList.remove('sources-open');
      if (!isNarrow()) app.classList.remove('sidebar-open');
      syncScrim(); moveIndicator();
      $('#btn-sources').setAttribute('aria-expanded', sourcesVisible() ? 'true' : 'false');
      $('#btn-sidebar').setAttribute('aria-expanded', sidebarVisible() ? 'true' : 'false');
    });
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { loadDocs(); if (state.view === 'analytics') loadAnalytics(false); } });
    if (isOverlay()) $('#btn-sources').setAttribute('aria-expanded', 'false');
    $('#btn-sidebar').setAttribute('aria-expanded', sidebarVisible() ? 'true' : 'false');
    if (isOverlay()) $('#app').classList.add('no-sources');
  }


  /* ---------- theme ---------- */
  function setupTheme() {
    var root = document.documentElement, btn = $('#btn-theme');
    function sync() {
      var dark = root.getAttribute('data-theme') === 'dark';
      btn.setAttribute('aria-pressed', dark ? 'true' : 'false');
      btn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    }
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      store('ragbot.theme', next);
      sync();
    });
    sync();
  }

  /* ---------- init ---------- */
  function init() {
    setupTheme();
    setupChrome();
    setupTips();
    setupModelMenu();
    setupUpload();
    setupChat();
    setupVoice();
    renderWelcome();
    renderHistory();
    updateSendState();
    icons();
    moveIndicator();
    loadConfig();
    loadDocs();
    $('#composer-input').focus();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  window.addEventListener('load', function () { icons(); moveIndicator(); });
})();
