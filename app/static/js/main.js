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
    const viewport = lightbox.querySelector("[data-lightbox-viewport]");

    let scale = 1;
    let translateX = 0;
    let translateY = 0;

    const pointers = new Map();
    let startTranslateX = 0;
    let startTranslateY = 0;
    let startScale = 1;
    let startDistance = 0;
    let startMidpoint = null;
    let lastMidpoint = null;

    const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

    const getViewportRect = () => (viewport || img)?.getBoundingClientRect();

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

    const zoomTo = (nextScale, clientX, clientY) => {
      if (!img) return;
      const rect = getViewportRect();
      if (!rect) return;

      const prevScale = scale;
      scale = clamp(nextScale, 1, 6);
      if (scale === prevScale) return;

      const originX = clientX ?? rect.left + rect.width / 2;
      const originY = clientY ?? rect.top + rect.height / 2;
      const dx = originX - (rect.left + rect.width / 2);
      const dy = originY - (rect.top + rect.height / 2);
      const ratio = scale / prevScale;

      translateX = translateX - dx * (ratio - 1);
      translateY = translateY - dy * (ratio - 1);
      applyTransform();
    };

    const zoomBy = (delta, clientX, clientY) => {
      zoomTo(scale + delta, clientX, clientY);
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

    (viewport || img)?.addEventListener(
      "wheel",
      (event) => {
        if (lightbox.hidden) return;
        event.preventDefault();
        const direction = event.deltaY < 0 ? 1 : -1;
        zoomBy(direction * 0.2, event.clientX, event.clientY);
      },
      { passive: false }
    );

    const pointerTarget = viewport || img;
    pointerTarget?.addEventListener("pointerdown", (event) => {
      if (!img || lightbox.hidden) return;
      event.preventDefault();
      pointerTarget.setPointerCapture?.(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

      startTranslateX = translateX;
      startTranslateY = translateY;
      startScale = scale;

      if (pointers.size === 1) {
        img.style.cursor = scale > 1 ? "grabbing" : "default";
      }

      if (pointers.size === 2) {
        const [a, b] = Array.from(pointers.values());
        startDistance = Math.hypot(b.x - a.x, b.y - a.y);
        startMidpoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        lastMidpoint = startMidpoint;
      }
    });

    pointerTarget?.addEventListener("pointermove", (event) => {
      if (!img || lightbox.hidden) return;
      if (!pointers.has(event.pointerId)) return;
      if (pointers.size >= 1 && (scale > 1 || pointers.size === 2)) {
        event.preventDefault();
      }
      const prevPoint = pointers.get(event.pointerId);
      pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });

      if (pointers.size === 1) {
        if (scale <= 1) return;
        if (!prevPoint) return;
        const dx = event.clientX - prevPoint.x;
        const dy = event.clientY - prevPoint.y;
        translateX += dx;
        translateY += dy;
        applyTransform();
        return;
      }

      if (pointers.size === 2) {
        const [a, b] = Array.from(pointers.values());
        const currentDistance = Math.hypot(b.x - a.x, b.y - a.y);
        const midpoint = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const scaleFactor = startDistance ? currentDistance / startDistance : 1;
        const nextScale = clamp(startScale * scaleFactor, 1, 6);

        zoomTo(nextScale, midpoint.x, midpoint.y);

        if (lastMidpoint) {
          translateX += midpoint.x - lastMidpoint.x;
          translateY += midpoint.y - lastMidpoint.y;
        }
        lastMidpoint = midpoint;
        applyTransform();
        return;
      }
    });

    const clearPointer = (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.delete(event.pointerId);
      if (pointers.size < 2) {
        startMidpoint = null;
        lastMidpoint = null;
        startDistance = 0;
        startScale = scale;
      }
      applyTransform();
    };

    pointerTarget?.addEventListener("pointerup", clearPointer);
    pointerTarget?.addEventListener("pointercancel", clearPointer);

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
    const dialog = document.getElementById("documentsEditDialog");
    document.querySelectorAll("[data-docs-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (dialog && typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });
  };

  const initProfileEditor = () => {
    const dialog = document.getElementById("profileEditDialog");
    document.querySelectorAll("[data-profile-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (dialog && typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });
  };

  const initDialogCloseButtons = () => {
    document.querySelectorAll("[data-dialog-close]").forEach((button) => {
      button.addEventListener("click", () => {
        const dialog = button.closest("dialog");
        if (dialog && typeof dialog.close === "function") {
          dialog.close();
        }
      });
    });
  };

  window.togglePassword = (input) => {
    const type = input.type === "password" ? "text" : "password";
    input.type = type;
    const button = input.nextElementSibling;
    if (button && button.tagName === "BUTTON") {
      button.textContent = type === "password" ? "👁" : "🙈";
    }
  };

  const initLicenseRequiredPrompt = () => {
    const wrapper = document.querySelector("[data-license-required]");
    if (!wrapper) return;
    if (wrapper.dataset.licenseRequired !== "true") return;
    const dialog = document.getElementById("licenseRequiredDialog");
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    }
  };

  const initDescriptionRequiredPrompt = () => {
    const wrapper = document.querySelector("[data-description-required]");
    if (!wrapper) return;
    if (wrapper.dataset.descriptionRequired !== "true") return;
    const dialog = document.getElementById("descriptionRequiredDialog");
    if (dialog && typeof dialog.showModal === "function") {
      dialog.showModal();
    }
  };

  const initMessaging = () => {
    const navBadge = document.querySelector("[data-messages-unread]");
    const threadsList = document.querySelector("[data-threads-list]");
    const conversationPanel = document.querySelector("[data-conversation-panel]");
    const messagesList = document.querySelector("[data-messages-list]");
    const activeThreadId = conversationPanel?.dataset.activeThreadId;
    const sendForm = document.querySelector("[data-send-form]");
    let isSending = false;

    const setBadge = (count) => {
      if (!navBadge) return;
      const num = Number(count || 0);
      if (num > 0) {
        navBadge.hidden = false;
        navBadge.textContent = String(num);
      } else {
        navBadge.hidden = true;
      }
    };

    const fetchUnread = async () => {
      try {
        const res = await fetch("/api/messages/unread", {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const data = await res.json();
        setBadge(data.unread);
      } catch {
        // ignore
      }
    };

    const renderThreads = (threads) => {
      if (!threadsList) return;
      threadsList.innerHTML = "";
      threads.forEach((t) => {
        const a = document.createElement("a");
        a.className = "card";
        a.href = `/messages/${t._id}`;
        a.style.padding = "0.75rem";
        a.style.textDecoration = "none";
        a.dataset.threadLocked = t.locked ? "1" : "0";
        if (t.locked) {
          a.style.opacity = "0.6";
          a.style.cursor = "not-allowed";
        }
        if (t.unread_count > 0) {
          a.style.outline = "2px solid rgba(245, 158, 11, 0.35)";
        }

        const title = document.createElement("strong");
        title.style.display = "block";
        title.style.color = "inherit";
        title.textContent = t.title;
        a.appendChild(title);

        const sub = document.createElement("span");
        sub.className = "muted small";
        sub.textContent = "Open conversation";
        a.appendChild(sub);

        if (t.unread_count > 0) {
          const badge = document.createElement("span");
          badge.className = "badge";
          badge.style.marginLeft = "0.5rem";
          badge.textContent = String(t.unread_count);
          a.appendChild(badge);
        }

        threadsList.appendChild(a);
      });

      threadsList.querySelectorAll("[data-thread-locked='1'], [data-thread-locked='true'], [data-thread-locked='True']").forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          alert("Please wait for admin to verify your account.");
        });
      });
    };

    const refreshThreads = async () => {
      if (!threadsList) return;
      try {
        const res = await fetch("/api/messages/threads", {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const data = await res.json();
        renderThreads(data.threads || []);
      } catch {
        // ignore
      }
    };

    let lastSeen = null;
    const seen = new Set();

    if (messagesList) {
      messagesList.querySelectorAll("[data-created-at]").forEach((node) => {
        const key = node.dataset.createdAt;
        if (key) seen.add(key);
      });
    }

    const appendMessages = (msgs) => {
      if (!messagesList) return;
      msgs.forEach((m) => {
        const seenKey = m.created_at || null;
        if (seenKey && seen.has(seenKey)) {
          return;
        }

        const row = document.createElement("div");
        row.style.display = "flex";
        row.style.justifyContent = m.is_me ? "flex-end" : "flex-start";
        if (m.created_at) row.dataset.createdAt = m.created_at;

        const bubble = document.createElement("div");
        bubble.className = "card";
        bubble.style.padding = "0.6rem 0.75rem";
        bubble.style.maxWidth = "70%";

        const text = document.createElement("div");
        text.style.whiteSpace = "pre-wrap";
        text.textContent = m.text;
        bubble.appendChild(text);
        row.appendChild(bubble);
        messagesList.appendChild(row);

        if (seenKey) seen.add(seenKey);
        if (m.created_at) lastSeen = m.created_at;
      });
      messagesList.scrollTop = messagesList.scrollHeight;
    };

    const markRead = async () => {
      if (!activeThreadId) return;
      try {
        await fetch(`/api/messages/${activeThreadId}/read`, { method: "POST" });
      } catch {
        // ignore
      }
    };

    const pollActiveConversation = async () => {
      if (!activeThreadId || !messagesList) return;
      const url = new URL(
        `/api/messages/${activeThreadId}/since`,
        window.location.origin
      );
      if (lastSeen) url.searchParams.set("after", lastSeen);
      try {
        const res = await fetch(url.toString(), {
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const data = await res.json();
        const msgs = data.messages || [];
        if (msgs.length) {
          appendMessages(msgs);
          await markRead();
        }
      } catch {
        // ignore
      }
    };

    fetchUnread();
    if (threadsList) {
      threadsList.querySelectorAll("[data-thread-locked='1']").forEach((link) => {
        link.addEventListener("click", (event) => {
          event.preventDefault();
          alert("Please wait for admin to verify your account.");
        });
      });
    }
    if (threadsList) {
      refreshThreads();
      setInterval(refreshThreads, 2500);
    }
    if (navBadge) {
      setInterval(fetchUnread, 2500);
    }
    if (activeThreadId && messagesList) {
      const existing = Array.from(
        messagesList.querySelectorAll("[data-created-at]")
      );
      if (existing.length) {
        lastSeen = existing[existing.length - 1].dataset.createdAt || null;
      }
      markRead();
      setInterval(pollActiveConversation, 2000);
    }

    if (sendForm && activeThreadId && messagesList) {
      sendForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (isSending) return;
        const input = sendForm.querySelector("input[name='text']");
        const submitButton = sendForm.querySelector("button[type='submit']");
        const text = (input?.value || "").trim();
        if (!text) return;

        isSending = true;
        if (input) {
          input.value = "";
          input.disabled = true;
        }
        if (submitButton) submitButton.disabled = true;

        const payload = new FormData();
        payload.append("text", text);
        try {
          const res = await fetch(`/api/messages/${activeThreadId}/send`, {
            method: "POST",
            body: payload,
            headers: { Accept: "application/json" },
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            alert(data.error || "Could not send message");
            if (input) input.value = text;
            return;
          }
          if (data.message) {
            appendMessages([data.message]);
          }
          await markRead();
          refreshThreads();
          fetchUnread();
        } catch {
          alert("Could not send message");
          if (input) input.value = text;
        } finally {
          isSending = false;
          if (input) input.disabled = false;
          if (submitButton) submitButton.disabled = false;
          if (input) input.focus();
        }
      });
    }
  };

  const initDescriptionEditor = () => {
    const dialog = document.getElementById("descriptionEditDialog");
    if (!dialog) return;
    document.querySelectorAll("[data-description-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (typeof dialog.showModal === "function") {
          dialog.showModal();
        }
      });
    });
  };

  const initDoctorCards = () => {
    if (!document.querySelector("[data-doctor-card]")) return;

    const descriptionDialog = document.getElementById("doctorDescriptionDialog");
    const descriptionTitle = descriptionDialog?.querySelector("[data-doctor-description-title]");
    const descriptionBody = descriptionDialog?.querySelector("[data-doctor-description-body]");

    const reviewDialog = document.getElementById("reviewDialog");
    const reviewDoctor = reviewDialog?.querySelector("[data-review-doctor]");
    const reviewStars = reviewDialog?.querySelector("[data-review-stars]");
    const submitReview = reviewDialog?.querySelector("[data-submit-review]");
    const reviewMessage = reviewDialog?.querySelector("[data-review-message]");
    const reviewMessageBtn = reviewDialog?.querySelector("[data-review-message-btn]");

    let activeCard = null;
    let selectedRating = 0;

    const renderStars = (container, rating) => {
      if (!container) return;
      const full = "★".repeat(Math.max(0, Math.min(5, rating)));
      const empty = "☆".repeat(Math.max(0, 5 - Math.max(0, Math.min(5, rating))));
      container.textContent = `${full}${empty}`;
    };

    document.querySelectorAll("[data-doctor-card]").forEach((card) => {
      const openReviewBtn = card.querySelector("[data-open-review]");
      const starsEl = card.querySelector("[data-stars]");
      const countEl = card.querySelector("[data-review-count]");

      const rating = Number(card.dataset.rating || 0);
      const count = Number(card.dataset.reviewCount || 0);
      renderStars(starsEl, rating);
      if (countEl) countEl.textContent = `(${count})`;

      card.addEventListener("click", (event) => {
        if (event.target && (event.target.closest("a") || event.target.closest("button"))) return;
        if (!descriptionDialog || typeof descriptionDialog.showModal !== "function") return;
        const name = card.dataset.doctorName || "Doctor details";
        const desc = (card.dataset.doctorDescription || "").trim();
        if (descriptionTitle) descriptionTitle.textContent = name;
        if (descriptionBody) descriptionBody.textContent = desc || "No description provided yet.";
        descriptionDialog.showModal();
      });

      openReviewBtn?.addEventListener("click", () => {
        if (!reviewDialog || typeof reviewDialog.showModal !== "function") return;
        activeCard = card;
        selectedRating = 0;
        if (reviewDoctor) reviewDoctor.textContent = card.dataset.doctorName || "";
        if (reviewMessage) reviewMessage.value = "";
        if (reviewMessageBtn) {
          reviewMessageBtn.textContent = "Send message";
          const doctorId = card.dataset.doctorId;
          reviewMessageBtn.href = doctorId ? `/messages/start/${doctorId}` : "/messages";
        }
        reviewDialog.showModal();
      });
    });

    reviewStars?.addEventListener("click", (event) => {
      const btn = event.target?.closest("[data-star]");
      if (!btn) return;
      selectedRating = Number(btn.dataset.star || 0);
      reviewStars.querySelectorAll("[data-star]").forEach((starBtn) => {
        const on = Number(starBtn.dataset.star || 0) <= selectedRating;
        starBtn.style.color = on ? "#f59e0b" : "rgba(27, 36, 64, 0.35)";
      });
    });

    submitReview?.addEventListener("click", () => {
      if (!activeCard || !selectedRating) return;
      const starsEl = activeCard.querySelector("[data-stars]");
      const countEl = activeCard.querySelector("[data-review-count]");
      const prevCount = Number(activeCard.dataset.reviewCount || 0);
      const prevRating = Number(activeCard.dataset.rating || 0);
      const newCount = prevCount + 1;
      const newRating = Math.round(((prevRating * prevCount) + selectedRating) / newCount);
      activeCard.dataset.reviewCount = String(newCount);
      activeCard.dataset.rating = String(newRating);
      renderStars(starsEl, newRating);
      if (countEl) countEl.textContent = `(${newCount})`;
      reviewDialog?.close?.();
    });
  };

  const initAdminKebabMenus = () => {
    if (!document.querySelector("[data-admin-dashboard]")) return;

    const detailsDialog = document.getElementById("adminDoctorDetailsDialog");
    const reasonDialog = document.getElementById("adminReasonDialog");
    const reasonForm = reasonDialog?.querySelector("[data-admin-reason-form]");
    const roleDialog = document.getElementById("adminRoleDialog");
    const roleForm = roleDialog?.querySelector("[data-admin-role-form]");

    const fillDetails = (menu) => {
      if (!detailsDialog) return;
      detailsDialog.querySelector("[data-admin-details-title]").textContent = menu.dataset.doctorName || "Doctor details";
      detailsDialog.querySelector("[data-admin-details-email]").textContent = menu.dataset.doctorEmail || "";
      detailsDialog.querySelector("[data-admin-details-phone]").textContent = menu.dataset.doctorPhone || "";
      detailsDialog.querySelector("[data-admin-details-specialization]").textContent = menu.dataset.doctorSpecialization || "";
      detailsDialog.querySelector("[data-admin-details-license]").textContent = menu.dataset.doctorLicense || "";
      detailsDialog.querySelector("[data-admin-details-city]").textContent = menu.dataset.doctorCity || "";
      detailsDialog.querySelector("[data-admin-details-pin]").textContent = menu.dataset.doctorPin || "";
      detailsDialog.querySelector("[data-admin-details-description]").textContent = (menu.dataset.doctorDescription || "").trim() || "No description";

      const selfBtn = detailsDialog.querySelector('[data-admin-doc="self"]');
      const degreeBtn = detailsDialog.querySelector('[data-admin-doc="degree"]');
      const visitingBtn = detailsDialog.querySelector('[data-admin-doc="visiting"]');

      const setDoc = (btn, src) => {
        const img = btn?.querySelector("img");
        if (!btn || !img) return;
        if (src) {
          img.src = src;
          btn.hidden = false;
          btn.dataset.zoomSrc = src;
        } else {
          btn.hidden = true;
        }
      };
      setDoc(selfBtn, menu.dataset.selfPhoto);
      setDoc(degreeBtn, menu.dataset.degreePhoto);
      setDoc(visitingBtn, menu.dataset.visitingCard);
    };

    const openReason = (action, userId) => {
      if (!reasonDialog || typeof reasonDialog.showModal !== "function") return;
      const title = reasonDialog.querySelector("[data-admin-reason-title]");
      if (title) title.textContent = `Reason for ${action}`;
      reasonForm.elements.user_id.value = userId;
      reasonForm.elements.action.value = action;
      reasonForm.elements.reason.value = "";
      reasonDialog.showModal();
    };

    const openRoleDialog = (menu) => {
      if (!roleDialog || typeof roleDialog.showModal !== "function" || !roleForm) return;
      const title = roleDialog.querySelector("[data-admin-role-title]");
      if (title) {
        const name = menu.dataset.userName || "User";
        title.textContent = `Change role: ${name}`;
      }
      roleForm.elements.user_id.value = menu.dataset.userId;
      const current = (menu.dataset.userRole || "user").toLowerCase();
      roleForm.elements.role.value = current;
      roleDialog.showModal();
    };

    document.addEventListener("click", (event) => {
      const btn = event.target?.closest("[data-kebab-btn]");
      if (btn) {
        const kebab = btn.closest(".kebab");
        const menu = kebab?.querySelector("[data-kebab-menu]");
        if (!menu) return;
        const isHidden = menu.hasAttribute("hidden");
        document.querySelectorAll("[data-kebab-menu]").forEach((m) => m.setAttribute("hidden", ""));
        if (isHidden) menu.removeAttribute("hidden");
        return;
      }

      if (!event.target?.closest("[data-kebab-menu]")) {
        document.querySelectorAll("[data-kebab-menu]").forEach((m) => m.setAttribute("hidden", ""));
      }
    });

    document.querySelectorAll("[data-kebab-menu]").forEach((menu) => {
      menu.querySelector("[data-admin-role]")?.addEventListener("click", () => {
        menu.setAttribute("hidden", "");
        openRoleDialog(menu);
      });

      menu.querySelector("[data-admin-delete]")?.addEventListener("click", async () => {
        menu.setAttribute("hidden", "");
        const name = menu.dataset.userName || "this user";
        const ok = window.confirm(`Remove ${name}? This deletes the account and chats.`);
        if (!ok) return;
        const response = await fetch("/api/auth/admin/delete-user", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: menu.dataset.userId }),
        });
        if (response.ok) window.location.reload();
        else alert((await response.text()) || "Could not delete user.");
      });

      menu.querySelector("[data-admin-view]")?.addEventListener("click", () => {
        fillDetails(menu);
        detailsDialog?.showModal?.();
        menu.setAttribute("hidden", "");
      });

      menu.querySelector("[data-admin-approve]")?.addEventListener("click", async () => {
        menu.setAttribute("hidden", "");
        const response = await fetch("/api/auth/admin/approve-doctor", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user_id: menu.dataset.doctorId }),
        });
        if (response.ok) window.location.reload();
        else alert((await response.text()) || "Could not approve doctor.");
      });

      menu.querySelector("[data-admin-reject]")?.addEventListener("click", () => {
        menu.setAttribute("hidden", "");
        openReason("reject", menu.dataset.doctorId);
      });

      menu.querySelector("[data-admin-unverify]")?.addEventListener("click", () => {
        menu.setAttribute("hidden", "");
        openReason("unverify", menu.dataset.doctorId);
      });

      menu.querySelector("[data-admin-restrict]")?.addEventListener("click", () => {
        menu.setAttribute("hidden", "");
        openReason("restrict", menu.dataset.doctorId);
      });
    });

    reasonForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const userId = form.elements.user_id.value;
      const action = form.elements.action.value;
      const reason = form.elements.reason.value;

      const endpointMap = {
        reject: "/api/auth/admin/reject-doctor",
        unverify: "/api/auth/admin/unverify-doctor",
        restrict: "/api/auth/admin/restrict-doctor",
      };
      const url = endpointMap[action];
      if (!url) return;

      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, reason }),
      });

      if (response.ok) {
        window.location.reload();
      } else {
        alert((await response.text()) || "Request failed");
      }
    });

    roleForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = event.currentTarget;
      const userId = form.elements.user_id.value;
      const role = form.elements.role.value;
      const response = await fetch("/api/auth/admin/update-role", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, role }),
      });
      if (response.ok) {
        window.location.reload();
      } else {
        alert((await response.text()) || "Could not update role.");
      }
    });
  };

  const initAdminActions = () => {
    if (!document.querySelector("[data-admin-dashboard]")) return;

    window.approveDoctor = async (userId) => {
      if (!userId) return;
      const response = await fetch("/api/auth/admin/approve-doctor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      if (response.ok) {
        window.location.reload();
      } else {
        const msg = await response.text();
        alert(msg || "Could not approve doctor. Please try again.");
      }
    };

    window.rejectDoctor = async (userId) => {
      if (!userId) return;
      const response = await fetch("/api/auth/admin/reject-doctor", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId }),
      });
      if (response.ok) {
        window.location.reload();
      } else {
        const msg = await response.text();
        alert(msg || "Could not reject doctor. Please try again.");
      }
    };
  };

  initAdminTabs();
  initLoggedInSearch();
  initDocumentZoom();
  initDocsEditor();
  initProfileEditor();
  initDialogCloseButtons();
  initAdminActions();
  initLicenseRequiredPrompt();
  initDescriptionRequiredPrompt();
  initDescriptionEditor();
  initDoctorCards();
  initAdminKebabMenus();
  initMessaging();
});
