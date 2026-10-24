document.addEventListener('DOMContentLoaded', () => {
  const body   = document.getElementById('lignes-body');
  const total  = document.getElementById('id_lignes-TOTAL_FORMS');
  const tpl    = document.getElementById('empty-ligne');
  const tarifs = JSON.parse(document.getElementById('tarifs-data').textContent);

  document.getElementById('add-ligne').addEventListener('click', () => {
    const idx = parseInt(total.value, 10);
    body.insertAdjacentHTML('beforeend', tpl.innerHTML.replace(/__prefix__/g, idx));
    total.value = idx + 1;
  });

  body.addEventListener('change', (e) => {
    if (!e.target.name || !e.target.name.endsWith('-tarif')) return;
    const t = tarifs[e.target.value];
    if (!t) return;
    const row = e.target.closest('tr');
    row.querySelector('[name$="-description"]').value = t.libelle;
    row.querySelector('[name$="-prix_unitaire"]').value = t.prix;
  });
});