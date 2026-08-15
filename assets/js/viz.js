/* ============================================================
   viz.js - chart + interaction helpers. No dependencies.
   Every chart gets: a legend when it has 2+ series, a hover
   tooltip, and a table view fallback.
   ============================================================ */
(function () {
  'use strict';

  var tip = null;
  function tipEl() {
    if (!tip) {
      tip = document.createElement('div');
      tip.className = 'tip';
      tip.setAttribute('role', 'status');
      document.body.appendChild(tip);
    }
    return tip;
  }
  function showTip(html, x, y) {
    var t = tipEl();
    t.innerHTML = html;
    t.classList.add('on');
    var r = t.getBoundingClientRect();
    var left = x + 14, top = y - r.height - 12;
    if (left + r.width > window.innerWidth - 8) left = x - r.width - 14;
    if (left < 8) left = 8;
    if (top < 8) top = y + 18;
    t.style.left = left + 'px';
    t.style.top = top + 'px';
  }
  function hideTip() { if (tip) tip.classList.remove('on'); }
  window.addEventListener('scroll', hideTip, { passive: true });

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }
  function tipRows(title, rows) {
    var h = '<div class="tip-t">' + esc(title) + '</div>';
    rows.forEach(function (r) {
      h += '<div class="tip-r"><span class="k">' +
        (r.color ? '<span class="tip-sw" style="background:' + esc(r.color) + '"></span>' : '') +
        esc(r.k) + '</span><span class="v">' + esc(r.v) + '</span></div>';
    });
    return h;
  }

  function bindTips(root) {
    (root || document).querySelectorAll('[data-tip-title]').forEach(function (el) {
      if (el.__tipBound) return;
      el.__tipBound = true;
      var rows;
      try { rows = JSON.parse(el.getAttribute('data-tip-rows') || '[]'); } catch (e) { rows = []; }
      var html = tipRows(el.getAttribute('data-tip-title'), rows);
      function move(ev) {
        var p = ev.touches ? ev.touches[0] : ev;
        showTip(html, p.clientX, p.clientY);
      }
      el.addEventListener('mouseenter', move);
      el.addEventListener('mousemove', move);
      el.addEventListener('mouseleave', hideTip);
      el.addEventListener('focus', function () {
        var r = el.getBoundingClientRect();
        showTip(html, r.left + r.width / 2, r.top);
      });
      el.addEventListener('blur', hideTip);
      if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '0');
    });
  }

  function bindTableViews(root) {
    (root || document).querySelectorAll('[data-tableview]').forEach(function (btn) {
      if (btn.__tvBound) return;
      btn.__tvBound = true;
      var target = document.getElementById(btn.getAttribute('data-tableview'));
      if (!target) return;
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-controls', target.id);
      btn.addEventListener('click', function () {
        var open = !target.hasAttribute('hidden');
        if (open) { target.setAttribute('hidden', ''); btn.textContent = btn.dataset.labelShow || 'Table'; }
        else { target.removeAttribute('hidden'); btn.textContent = btn.dataset.labelHide || 'Hide table'; }
        btn.setAttribute('aria-expanded', String(!open));
      });
    });
  }

  function bindBars(root) {
    var els = (root || document).querySelectorAll('.bar-fill[data-w]');
    if (!els.length) return;
    if (!('IntersectionObserver' in window) ||
        window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      els.forEach(function (b) { b.style.width = b.dataset.w; });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.style.width = e.target.dataset.w;
        io.unobserve(e.target);
      });
    }, { threshold: 0.15 });
    els.forEach(function (b) { b.style.width = '0'; io.observe(b); });
  }

  function fmt(n, d) {
    if (n === null || n === undefined || isNaN(n)) return 'n/a';
    d = d === undefined ? (Math.abs(n) >= 100 ? 0 : Math.abs(n) >= 10 ? 1 : 2) : d;
    return Number(n).toLocaleString('en-GB', { minimumFractionDigits: d, maximumFractionDigits: d });
  }

  function bindReveal(root) {
    var els = (root || document).querySelectorAll('[data-reveal]');
    if (!els.length) return;
    if (!('IntersectionObserver' in window)) {
      els.forEach(function (e) { e.style.opacity = 1; }); return;
    }
    var io = new IntersectionObserver(function (en) {
      en.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.style.transition = 'opacity .5s ease, transform .5s ease';
        e.target.style.opacity = 1;
        e.target.style.transform = 'none';
        io.unobserve(e.target);
      });
    }, { threshold: 0.06 });
    els.forEach(function (e) {
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { e.style.opacity = 1; return; }
      e.style.opacity = 0; e.style.transform = 'translateY(10px)';
      io.observe(e);
    });
  }

  function init(root) {
    bindTips(root); bindTableViews(root); bindBars(root); bindReveal(root);
  }

  window.Viz = { init: init, fmt: fmt, tipRows: tipRows, showTip: showTip, hideTip: hideTip, esc: esc };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(document); });
  } else { init(document); }
})();
