document.addEventListener("DOMContentLoaded", () => {
  const initDobFields = () => {
    const wrappers = document.querySelectorAll("[data-dob-field]");

    const isValidDate = (value) => {
      if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
        return false;
      }
      const [year, month, day] = value.split("-").map(Number);
      const date = new Date(Date.UTC(year, month - 1, day));
      return (
        date.getUTCFullYear() === year &&
        date.getUTCMonth() === month - 1 &&
        date.getUTCDate() === day
      );
    };

    wrappers.forEach((wrapper) => {
      const dateInput = wrapper.querySelector('input[type="date"]');
      const textInput = wrapper.querySelector("[data-dob-text]");
      if (!dateInput || !textInput) return;

      const syncText = () => {
        if (dateInput.value) {
          textInput.value = dateInput.value;
          wrapper.classList.add("filled");
        }
      };

      dateInput.addEventListener("change", () => {
        syncText();
        textInput.setCustomValidity("");
      });

      textInput.addEventListener("input", () => {
        const value = textInput.value.trim();
        if (!value) {
          dateInput.value = "";
          textInput.setCustomValidity("");
          wrapper.classList.remove("filled");
          return;
        }
        if (isValidDate(value)) {
          dateInput.value = value;
          textInput.setCustomValidity("");
          wrapper.classList.add("filled");
        } else {
          textInput.setCustomValidity("Enter date as YYYY-MM-DD");
        }
      });

      textInput.addEventListener("blur", () => {
        if (isValidDate(textInput.value.trim()) || !textInput.value.trim()) {
          textInput.setCustomValidity("");
        }
      });

      syncText();
    });
  };

  initDobFields();

  const profileCard = document.querySelector(".profile-card");
  if (profileCard?.dataset.pendingVerification === "true") {
    const dialog = document.getElementById("pendingVerificationDialog");
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    }
  }

  const profileMenus = document.querySelectorAll(".profile-menu");

  profileMenus.forEach((menu) => {
    const icon = menu.querySelector(".profile-icon");
    const dropdown = menu.querySelector(".dropdown");

    const toggleMenu = (open) => {
      menu.classList.toggle("open", open);
    };

    const handleOutsideClick = (event) => {
      if (!menu.contains(event.target)) {
        toggleMenu(false);
      }
    };

    icon?.addEventListener("click", () => {
      const isOpen = menu.classList.contains("open");
      toggleMenu(!isOpen);
    });

    icon?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const isOpen = menu.classList.contains("open");
        toggleMenu(!isOpen);
      }
      if (event.key === "Escape") {
        toggleMenu(false);
      }
    });

    document.addEventListener("click", handleOutsideClick);
  });

  const pendingSection = document.querySelector(
    "[data-pending-verification='true']"
  );
  if (pendingSection) {
    const dialog = pendingSection.querySelector(
      "#pendingVerificationDialog"
    );
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    }
  }

  document.querySelectorAll("[data-action='logout']").forEach((button) => {
    button.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST" });
      window.location.href = "/";
    });
  });

  const initAdminTabs = () => {
    document.querySelectorAll("[data-tab-group]").forEach((group) => {
      const buttons = group.querySelectorAll("[data-tab-target]");
      const dashboard = group.closest("[data-admin-dashboard]") || document;
      const panels = dashboard.querySelectorAll("[data-tab-panel]");

      const activateTab = (target) => {
        buttons.forEach((btn) => {
          btn.classList.toggle("active", btn.dataset.tabTarget === target);
        });
        panels.forEach((panel) => {
          panel.classList.toggle("active", panel.dataset.tabPanel === target);
        });
      };

      buttons.forEach((btn) => {
        btn.addEventListener("click", () => {
          const target = btn.dataset.tabTarget;
          if (target) {
            activateTab(target);
          }
        });
      });
    });
  };

  initAdminTabs();
});
