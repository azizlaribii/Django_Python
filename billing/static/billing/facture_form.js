document.addEventListener('DOMContentLoaded', () => {
  const body   = document.getElementById('lignes-body');
  const total  = document.getElementById('id_lignes-TOTAL_FORMS');
  const tpl    = document.getElementById('empty-ligne');
  const addBtn = document.getElementById('add-ligne');
  const tarifs = JSON.parse(document.getElementById('tarifs-data').textContent);

  // ── Ajouter une ligne ──
  addBtn.addEventListener('click', () => {
    const idx = parseInt(total.value, 10);
    body.insertAdjacentHTML('beforeend', tpl.innerHTML.replace(/__prefix__/g, idx));
    total.value = idx + 1;
  });

  // ── Le choix d'un tarif remplit description et prix ──
  body.addEventListener('change', (e) => {
    if (!e.target.name || !e.target.name.endsWith('-tarif')) return;
    const t = tarifs[e.target.value];
    if (!t) return;
    const row = e.target.closest('tr');
    row.querySelector('[name$="-description"]').value = t.libelle;
    row.querySelector('[name$="-prix_unitaire"]').value = t.prix;
  });

  // ── Suggestion IA ──
  const btn = document.getElementById('ia-btn');
  if (!btn) return;
  const status = document.getElementById('ia-status');
  const csrf = document.querySelector('[name=csrfmiddlewaretoken]').value;

  function ligneLibre() {
    const rows = [...body.querySelectorAll('tr.ligne')];
    let row = rows.find(r =>
      !r.querySelector('[name$="-tarif"]').value &&
      !r.querySelector('[name$="-description"]').value);
    if (!row) {
      addBtn.click();
      const all = body.querySelectorAll('tr.ligne');
      row = all[all.length - 1];
    }
    return row;
  }

  btn.addEventListener('click', async () => {
    const texte = document.getElementById('ia-texte').value.trim();
    if (!texte) { status.textContent = 'Saisissez un texte.'; return; }
    btn.disabled = true;
    status.textContent = 'Analyse en cours…';
    try {
      const r = await fetch(btn.dataset.url, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf, 'Content-Type': 'application/x-www-form-urlencoded'},
        body: new URLSearchParams({texte}),
      });
      const data = await r.json();
      if (!r.ok) { status.textContent = data.erreur || 'Erreur.'; return; }
      if (!data.lignes.length) { status.textContent = 'Aucun tarif correspondant trouvé.'; return; }
      data.lignes.forEach(l => {
        const row = ligneLibre();
        const sel = row.querySelector('[name$="-tarif"]');
        sel.value = String(l.tarif_id);
        sel.dispatchEvent(new Event('change', {bubbles: true}));
        row.querySelector('[name$="-quantite"]').value = l.quantite;
      });
      status.textContent = data.lignes.length + ' ligne(s) proposée(s). Vérifiez avant d’enregistrer.';
    } catch (err) {
      console.error(err);
      status.textContent = 'Service indisponible. Ajoutez les lignes manuellement.';
    } finally {
      btn.disabled = false;
    }
  });
});