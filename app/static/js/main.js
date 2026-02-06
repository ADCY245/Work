document.addEventListener("DOMContentLoaded", () => {
  const initDobFields = () => {
    const wrappers = document.querySelectorAll("[data-dob-field]");

    const formatDobInput = (value) => {
      const digits = value.replace(/\D/g, "").slice(0, 8);
      const segments = [];
      if (digits.length > 0) {
        segments.push(digits.slice(0, Math.min(2, digits.length)));
      }
      if (digits.length >= 3) {
        segments.push(digits.slice(2, Math.min(4, digits.length)));
      } else if (digits.length > 2) {
        segments.push(digits.slice(2));
      }
      if (digits.length >= 5) {
        segments.push(digits.slice(4));
      }
      return segments.join("-");
    };

    const displayToIso = (value) => {
      const match = value.match(/^(\d{2})-(\d{2})-(\d{4})$/);
      if (!match) return null;
      const [, day, month, year] = match;
      return `${year}-${month}-${day}`;
    };

    const isoToDisplay = (value) => {
      const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
      if (!match) return "";
      const [, year, month, day] = match;
      return `${day}-${month}-${year}`;
    };

    const isValidDisplayDate = (value) => {
      const iso = displayToIso(value);
      if (!iso) return false;
      const [year, month, day] = iso.split("-").map(Number);
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
      const hiddenInput = wrapper.querySelector("[data-dob-hidden]");
      if (!dateInput || !textInput || !hiddenInput) return;

      const syncText = () => {
        if (dateInput.value) {
          textInput.value = isoToDisplay(dateInput.value);
          hiddenInput.value = dateInput.value;
          wrapper.classList.add("filled");
        } else {
          hiddenInput.value = "";
        }
      };

      dateInput.addEventListener("change", () => {
        syncText();
        textInput.setCustomValidity("");
      });

      textInput.addEventListener("input", () => {
        const formatted = formatDobInput(textInput.value);
        textInput.value = formatted;
        if (!formatted) {
          dateInput.value = "";
          hiddenInput.value = "";
          textInput.setCustomValidity("");
          wrapper.classList.remove("filled");
          return;
        }
        if (formatted.length === 10 && isValidDisplayDate(formatted)) {
          const iso = displayToIso(formatted);
          dateInput.value = iso;
          hiddenInput.value = iso;
          textInput.setCustomValidity("");
          wrapper.classList.add("filled");
        } else if (formatted.length === 10) {
          textInput.setCustomValidity("Enter date as DD-MM-YYYY");
        } else {
          textInput.setCustomValidity("");
          hiddenInput.value = "";
        }
      });

      textInput.addEventListener("blur", () => {
          const value = textInput.value.trim();
        if (isValidDisplayDate(value) || !value) {
          textInput.setCustomValidity("");
          if (!value) {
            hiddenInput.value = "";
          }
        }
      });

      syncText();
    });
  };

  initDobFields();

  const initLoggedInSearch = () => {
    document.querySelectorAll("[data-search-toggle]").forEach((button) => {
      const container = button.closest(".logged-in-search");
      if (!container) return;
      const panel = container.querySelector("[data-search-panel]");
      if (!panel) return;

      const updateState = (expanded) => {
        button.setAttribute("aria-expanded", expanded ? "true" : "false");
        panel.hidden = !expanded;
      };

      const hasPrefill = Array.from(panel.querySelectorAll("input")).some(
        (input) => input.value.trim()
      );
      if (hasPrefill) {
        updateState(true);
      } else {
        updateState(false);
      }

      button.addEventListener("click", () => {
        const expanded = panel.hidden;
        updateState(expanded);
        if (expanded) {
          panel.querySelector("input")?.focus();
        }
      });
    });
  };

  const initDocumentZoom = () => {
    const lightbox = document.querySelector("[data-image-lightbox]");
    if (!lightbox) return;
    const img = lightbox.querySelector("[data-lightbox-img]");
    const caption = lightbox.querySelector("[data-lightbox-caption]");
    const closeTargets = lightbox.querySelectorAll("[data-lightbox-close]");
    const btnZoomIn = lightbox.querySelector("[data-lightbox-zoom-in]");
    const btnZoomOut = lightbox.querySelector("[data-lightbox-zoom-out]");
    const btnReset = lightbox.querySelector("[data-lightbox-reset]");

    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let isDragging = false;
    let dragStartX = 0;
    let dragStartY = 0;

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    const applyTransform = () => {
      if (!img) return;
      img.style.transform = `translate(${translateX}px, ${translateY}px) scale(${scale})`;
      img.style.transformOrigin = "center center";
      img.style.cursor = scale > 1 ? "grab" : "default";
    };

    const resetTransform = () => {
      scale = 1;
      translateX = 0;
      translateY = 0;
      applyTransform();
    };

    const zoomBy = (delta, clientX, clientY) => {
      if (!img) return;
      const rect = img.getBoundingClientRect();
      const originX = clientX ?? rect.left + rect.width / 2;
      const originY = clientY ?? rect.top + rect.height / 2;

      const prevScale = scale;
      scale = clamp(scale + delta, 1, 6);
      const ratio = scale / prevScale;

      translateX = (translateX - (originX - rect.left - rect.width / 2)) * ratio + (originX - rect.left - rect.width / 2);
      translateY = (translateY - (originY - rect.top - rect.height / 2)) * ratio + (originY - rect.top - rect.height / 2);

      applyTransform();
    };

    const close = () => {
      lightbox.hidden = true;
      document.body.style.overflow = "";
      if (img) img.src = "";
      if (caption) caption.textContent = "";
      resetTransform();
    };

    const open = (src, label) => {
      if (!img || !src) return;
      img.src = src;
      if (caption) caption.textContent = label || "";
      lightbox.hidden = false;
      document.body.style.overflow = "hidden";
      resetTransform();
    };

    closeTargets.forEach((target) => target.addEventListener("click", close));
    lightbox.addEventListener("click", (event) => {
      if (event.target === lightbox.querySelector(".lightbox-backdrop")) {
        close();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !lightbox.hidden) {
        close();
      }
    });

    btnZoomIn?.addEventListener("click", () => zoomBy(0.5));
    btnZoomOut?.addEventListener("click", () => zoomBy(-0.5));
    btnReset?.addEventListener("click", () => resetTransform());

    img?.addEventListener(
      "wheel",
      (event) => {
        if (lightbox.hidden) return;
        event.preventDefault();
        const direction = event.deltaY < 0 ? 1 : -1;
        zoomBy(direction * 0.25, event.clientX, event.clientY);
      },
      { passive: false }
    );

    img?.addEventListener("mousedown", (event) => {
      if (scale <= 1) return;
      isDragging = true;
      dragStartX = event.clientX - translateX;
      dragStartY = event.clientY - translateY;
      img.style.cursor = "grabbing";
    });

    document.addEventListener("mousemove", (event) => {
      if (!isDragging) return;
      translateX = event.clientX - dragStartX;
      translateY = event.clientY - dragStartY;
      applyTransform();
    });

    document.addEventListener("mouseup", () => {
      if (!isDragging) return;
      isDragging = false;
      applyTransform();
    });

    document.querySelectorAll("[data-zoom-src]").forEach((element) => {
      element.addEventListener("click", () => {
        open(element.dataset.zoomSrc, element.dataset.zoomLabel);
      });
    });
  };

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

  const initDocsEditor = () => {
    document.querySelectorAll("[data-docs-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const section = document.querySelector("[data-docs-update]");
        if (!section) return;
        section.hidden = !section.hidden;
        if (!section.hidden) {
          section.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    });
  };

  initAdminTabs();
  initLoggedInSearch();
  initDocumentZoom();
  initDocsEditor();
});
