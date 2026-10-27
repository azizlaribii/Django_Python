/* Confort de lecture + lecture vocale des alertes (module Stocks) */
(function () {
  var KEY = 'stock_a11y', root = document.documentElement;
  var TAILLES = ['petit', 'normal', 'grand', 'tres-grand'];

  function charger() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch (e) { return {}; } }
  function sauver(p) { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) {} }
  var prefs = charger();

  function annoncer(msg) {
    var z = document.getElementById('a11y-annonce');
    if (z) { z.textContent = ''; setTimeout(function () { z.textContent = msg; }, 50); }
  }

  function appliquer() {
    root.setAttribute('data-taille', prefs.taille || 'normal');
    root.setAttribute('data-contraste', prefs.contraste ? 'eleve' : 'normal');
    var b = document.querySelector('[data-a11y="contraste"]');
    if (b) b.setAttribute('aria-pressed', prefs.contraste ? 'true' : 'false');
    var t = prefs.taille || 'normal';
    [['taille-normal', ['normal']], ['taille-plus', ['grand', 'tres-grand']], ['taille-moins', ['petit']]].forEach(function (x) {
      var el = document.querySelector('[data-a11y="' + x[0] + '"]');
      if (el) el.setAttribute('aria-pressed', x[1].indexOf(t) !== -1 ? 'true' : 'false');
    });
  }
  appliquer();

  document.addEventListener('click', function (e) {
    var el = e.target.closest ? e.target.closest('[data-a11y]') : null;
    if (!el) return;
    var action = el.getAttribute('data-a11y'), i = TAILLES.indexOf(prefs.taille || 'normal');
    if (action === 'taille-plus') { prefs.taille = TAILLES[Math.min(i + 1, 3)]; annoncer('Taille du texte : ' + prefs.taille.replace('-', ' ')); }
    else if (action === 'taille-moins') { prefs.taille = TAILLES[Math.max(i - 1, 0)]; annoncer('Taille du texte : ' + prefs.taille.replace('-', ' ')); }
    else if (action === 'taille-normal') { prefs.taille = 'normal'; annoncer('Taille du texte normale'); }
    else if (action === 'contraste') { prefs.contraste = !prefs.contraste; annoncer(prefs.contraste ? 'Contraste élevé activé' : 'Contraste élevé désactivé'); }
    else return;
    sauver(prefs); appliquer();
  });

  /* Lecture vocale des alertes (Web Speech API) */
  var btn = document.getElementById('btn-lire-alertes');
  if (btn) {
    if (!('speechSynthesis' in window)) { btn.hidden = true; }
    else {
      btn.addEventListener('click', function () {
        if (window.speechSynthesis.speaking) { window.speechSynthesis.cancel(); btn.setAttribute('aria-pressed', 'false'); return; }
        var u = new SpeechSynthesisUtterance(btn.getAttribute('data-lecture') || '');
        u.lang = 'fr-FR';
        u.onend = u.onerror = function () { btn.setAttribute('aria-pressed', 'false'); };
        btn.setAttribute('aria-pressed', 'true');
        window.speechSynthesis.speak(u);
      });
    }
  }

  /* Résumé d'erreurs : le focus y est placé pour que le lecteur d'écran l'annonce */
  var resume = document.getElementById('error-summary');
  if (resume) resume.focus();
})();
