(() => {
  function initialiseAnalysisSelection(form) {
    const bundles = [...form.querySelectorAll('input[name="bilans"][data-analysis-ids]')];
    const analyses = [...form.querySelectorAll('input[name="analyses"]')];
    if (!bundles.length || !analyses.length) return;

    const selectedBundleIds = () => new Set(
      bundles.filter(bundle => bundle.checked)
        .flatMap(bundle => bundle.dataset.analysisIds.split(/\s+/).filter(Boolean)),
    );
    const initiallyCovered = selectedBundleIds();
    const manuallySelected = new Set(
      analyses
        .filter(analysis => analysis.checked && !initiallyCovered.has(analysis.value))
        .map(analysis => analysis.value),
    );
    const excluded = new Set();

    function syncAnalysisSelection() {
      const covered = selectedBundleIds();
      analyses.forEach(analysis => {
        analysis.checked = manuallySelected.has(analysis.value)
          || (covered.has(analysis.value) && !excluded.has(analysis.value));
      });
    }

    bundles.forEach(bundle => bundle.addEventListener('change', () => {
      if (bundle.checked) {
        bundle.dataset.analysisIds.split(/\s+/).filter(Boolean)
          .forEach(id => excluded.delete(id));
      }
      syncAnalysisSelection();
    }));
    analyses.forEach(analysis => analysis.addEventListener('change', () => {
      if (analysis.checked) {
        manuallySelected.add(analysis.value);
        excluded.delete(analysis.value);
      } else {
        manuallySelected.delete(analysis.value);
        excluded.add(analysis.value);
      }
      syncAnalysisSelection();
    }));
    syncAnalysisSelection();
  }

  document.querySelectorAll('[data-request-dialog]').forEach(dialog => {
    const container = dialog.querySelector('[data-request-form-container]');
    const title = dialog.querySelector('[data-request-title]');
    const endpoint = dialog.dataset.endpoint;
    const buttons = document.querySelectorAll('[data-open-request-modal]');

    async function loadForm(button) {
      title.textContent = button.dataset.requestTitle || 'Demande d’analyse';
      container.textContent = 'Chargement du formulaire…';
      dialog.showModal();
      try {
        const response = await fetch(endpoint, {
          headers: {'X-Requested-With': 'XMLHttpRequest'},
        });
        if (!response.ok) throw new Error('Le formulaire ne peut pas être chargé.');
        container.innerHTML = await response.text();
        const form = container.querySelector('[data-prescription-form]');
        if (form) initialiseAnalysisSelection(form);
      } catch (error) {
        container.textContent = error.message;
      }
    }

    buttons.forEach(button => button.addEventListener('click', () => loadForm(button)));
    dialog.querySelectorAll('[data-close-request-dialog]').forEach(button => {
      button.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });
    container.addEventListener('click', event => {
      if (event.target.closest('[data-close-request]')) dialog.close();
    });
    container.addEventListener('submit', async event => {
      if (!event.target.matches('[data-prescription-form]')) return;
      event.preventDefault();
      const form = event.target;
      if (form.dataset.submitting === 'true') return;
      form.dataset.submitting = 'true';
      const submit = form.querySelector('button[type="submit"]');
      if (submit) {
        submit.disabled = true;
        submit.dataset.originalLabel = submit.textContent;
        submit.textContent = 'Enregistrement…';
      }
      try {
        const response = await fetch(form.action, {
          method: 'POST',
          body: new FormData(form),
          headers: {'X-Requested-With': 'XMLHttpRequest'},
        });
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
          const result = await response.json();
          if (!response.ok || !result.success) {
            throw new Error(result.error || 'La demande n’a pas pu être enregistrée.');
          }
          window.location.assign(result.redirect_url);
          return;
        }
        container.innerHTML = await response.text();
        const updatedForm = container.querySelector('[data-prescription-form]');
        if (updatedForm) initialiseAnalysisSelection(updatedForm);
      } catch (error) {
        const errors = form.querySelector('[data-prescription-error]');
        if (errors) {
          errors.textContent = error.message;
          errors.hidden = false;
        } else {
          container.textContent = error.message;
        }
      } finally {
        form.dataset.submitting = 'false';
        if (submit?.isConnected) {
          submit.disabled = false;
          submit.textContent = submit.dataset.originalLabel;
        }
      }
    });
  });

  document.querySelectorAll('[data-open-confirm-dialog]').forEach(button => {
    const dialog = document.querySelector(button.dataset.openConfirmDialog);
    if (!dialog) return;
    button.addEventListener('click', () => dialog.showModal());
    dialog.querySelectorAll('[data-close-confirm-dialog]').forEach(closeButton => {
      closeButton.addEventListener('click', () => dialog.close());
    });
    dialog.addEventListener('click', event => {
      if (event.target === dialog) dialog.close();
    });
  });
})();
