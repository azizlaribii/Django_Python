(() => {
  document.addEventListener("submit", event => {
    const form = event.target;
    if (
      form.matches("form[data-confirm-archive]")
      && !window.confirm(form.dataset.confirmArchive)
    ) {
      event.preventDefault();
    }
  });

  document.querySelectorAll("[data-catalog-dialog]").forEach(dialog => {
    const container = dialog.querySelector("[data-catalog-form-container]");
    const title = dialog.querySelector("[data-catalog-title]");

    async function loadForm(button) {
      title.textContent = button.dataset.catalogTitle || "Gestion du catalogue";
      container.textContent = "Chargement du formulaire…";
      dialog.showModal();
      try {
        const response = await fetch(button.dataset.catalogUrl, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok || response.redirected) {
          throw new Error("Le formulaire ne peut pas être chargé. Rechargez la page et réessayez.");
        }
        container.innerHTML = await response.text();
      } catch (error) {
        container.textContent = error.message;
      }
    }

    document.querySelectorAll("[data-open-catalog-dialog]").forEach(button => {
      button.addEventListener("click", () => loadForm(button));
    });
    dialog.addEventListener("click", event => {
      if (event.target === dialog || event.target.closest("[data-close-catalog-dialog]")) {
        dialog.close();
      }
    });
    container.addEventListener("submit", async event => {
      if (!event.target.matches("[data-catalog-form]")) return;
      event.preventDefault();
      const form = event.target;
      if (form.dataset.submitting === "true") return;
      form.dataset.submitting = "true";
      const submit = form.querySelector('button[type="submit"]');
      const originalLabel = submit?.textContent;
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Enregistrement…";
      }
      try {
        const response = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("application/json")) {
          const result = await response.json();
          if (!response.ok || !result.success) {
            throw new Error(result.error || "L’enregistrement a échoué.");
          }
          window.location.assign(result.redirect_url);
          return;
        }
        if (!response.ok || response.redirected) {
          throw new Error("Le formulaire n’a pas pu être enregistré. Rechargez la page et réessayez.");
        }
        container.innerHTML = await response.text();
      } catch (error) {
        const errorBox = container.querySelector("[data-catalog-error]");
        if (errorBox) {
          errorBox.textContent = error.message;
          errorBox.hidden = false;
        } else {
          container.textContent = error.message;
        }
      } finally {
        form.dataset.submitting = "false";
        if (submit?.isConnected) {
          submit.disabled = false;
          submit.textContent = originalLabel;
        }
      }
    });
  });
})();
