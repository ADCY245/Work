document.addEventListener("DOMContentLoaded", () => {
  const initPresenceHeartbeat = () => {
    const authRoot = document.querySelector("[data-auth='true']");
    if (!authRoot) return;
    const activeThreadId = document.querySelector("[data-conversation-panel]")?.dataset.activeThreadId || "";

    const ping = async () => {
      const payload = new FormData();
      if (activeThreadId) payload.append("thread_id", activeThreadId);
      try {
        await fetch("/api/messages/presence", {
          method: "POST",
          headers: { Accept: "application/json" },
          body: payload,
        });
      } catch {
        // ignore
      }
    };

    const goOffline = () => {
      const payload = new FormData();
      if (activeThreadId) payload.append("thread_id", activeThreadId);
      if (navigator.sendBeacon) {
        navigator.sendBeacon("/api/messages/presence/offline", payload);
        return;
      }
      fetch("/api/messages/presence/offline", {
        method: "POST",
        body: payload,
        keepalive: true,
      }).catch(() => {
        // ignore
      });
    };

    ping();
    setInterval(ping, 10000);
    window.addEventListener("pagehide", goOffline);
  };

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
      button.textContent = type === "password" ? "Show" : "Hide";
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
    const appointmentStrip = document.querySelector("[data-chat-appointments]");
    const appointmentDialog = document.querySelector("[data-appointment-dialog]");
    const appointmentForm = document.querySelector("[data-appointment-form]");
    const appointmentTitle = document.querySelector("[data-appointment-title]");
    const appointmentSubmit = document.querySelector("[data-appointment-submit]");
    const slotGrid = document.querySelector("[data-slot-grid]");
    const openAppointmentBtn = document.querySelector("[data-open-appointment]");
    const otherPresenceDot = document.querySelector("[data-other-presence-dot]");
    const otherPresenceLabel = document.querySelector("[data-other-presence-label]");
    let isSending = false;
    let calendarState = null;
    let calendarDisabled = false;
    let otherLastReadAt = conversationPanel?.dataset.otherLastReadAt || null;

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
          cache: "no-store",
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
        a.className = "thread-link";
        a.href = `/messages/${t._id}`;
        a.dataset.threadLocked = t.locked ? "1" : "0";
        if (t.unread_count > 0) {
          a.dataset.threadUnread = "1";
        }

        const titleRow = document.createElement("span");
        titleRow.className = "thread-title-row";
        const title = document.createElement("strong");
        title.textContent = t.title;
        const presence = document.createElement("span");
        presence.className = `presence-indicator${t.other_online ? " online" : ""}`;
        presence.setAttribute("aria-label", t.other_online ? "Online" : "Offline");
        titleRow.append(title, presence);
        a.appendChild(titleRow);

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
          cache: "no-store",
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
    const emptyState = messagesList?.querySelector(".muted");

    const messageKey = (messageLike) => messageLike?._id || messageLike?.created_at || null;

    const setOtherPresence = (isOnline) => {
      if (otherPresenceDot) {
        otherPresenceDot.classList.toggle("online", Boolean(isOnline));
      }
      if (otherPresenceLabel) {
        otherPresenceLabel.textContent = isOnline ? "Online" : "Offline";
      }
    };

    const updateSeenReceipts = (cutoff) => {
      if (!messagesList) return;
      otherLastReadAt = cutoff || otherLastReadAt;
      const cutoffTime = otherLastReadAt ? Date.parse(otherLastReadAt) : NaN;

      const myRows = Array.from(messagesList.querySelectorAll(".message-row.me[data-created-at]"));
      myRows.forEach((row) => row.querySelectorAll(".message-status").forEach((n) => n.remove()));

      const lastMyRow = myRows.length ? myRows[myRows.length - 1] : null;
      if (!lastMyRow) return;
      const createdAt = lastMyRow.dataset.createdAt ? Date.parse(lastMyRow.dataset.createdAt) : NaN;
      const statusText = Number.isFinite(cutoffTime) && Number.isFinite(createdAt) && cutoffTime >= createdAt
        ? "Seen"
        : "Sent";

      const status = document.createElement("div");
      status.className = "message-status";
      status.dataset.lastMeStatus = "true";
      status.textContent = statusText;
      lastMyRow.appendChild(status);
    };

    if (messagesList) {
      messagesList.querySelectorAll("[data-created-at], [data-message-id]").forEach((node) => {
        const key = node.dataset.messageId || node.dataset.createdAt;
        if (key) seen.add(key);
      });
      updateSeenReceipts(otherLastReadAt);
    }

    const appendMessages = (msgs) => {
      if (!messagesList) return;
      msgs.forEach((m) => {
        const seenKey = messageKey(m);
        if (seenKey && seen.has(seenKey)) {
          return;
        }

        emptyState?.remove();

        const row = document.createElement("div");
        row.className = m.is_me ? "message-row me" : "message-row";
        if (m._id) row.dataset.messageId = m._id;
        if (m.created_at) row.dataset.createdAt = m.created_at;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";

        const text = document.createElement("p");
        text.className = "message-text";
        text.textContent = (m.text || "").trim();
        bubble.appendChild(text);
        row.appendChild(bubble);
        messagesList.appendChild(row);

        if (seenKey) seen.add(seenKey);
        if (m.created_at) lastSeen = m.created_at;
      });
      updateSeenReceipts(otherLastReadAt);
      messagesList.scrollTop = messagesList.scrollHeight;
    };

    const slotLabel = (hour) => {
      const formatHour = (h) => {
        const normalized = ((h % 24) + 24) % 24;
        const suffix = normalized >= 12 ? "PM" : "AM";
        const display = normalized % 12 || 12;
        return `${display} ${suffix}`;
      };
      return `${formatHour(hour)}-${formatHour(hour + 1)}`;
    };

    const renderSlotGrid = () => {
      if (!slotGrid) return;
      slotGrid.innerHTML = "";
      for (let hour = 7; hour <= 21; hour += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "slot-chip";
        btn.dataset.slotHour = String(hour);
        btn.textContent = slotLabel(hour);
        btn.addEventListener("click", () => {
          btn.classList.toggle("selected");
        });
        slotGrid.appendChild(btn);
      }
    };

    const selectedSlots = () =>
      Array.from(slotGrid?.querySelectorAll(".slot-chip.selected") || [])
        .map((btn) => Number(btn.dataset.slotHour))
        .sort((a, b) => a - b);

    const openAppointmentDialog = (appointment = null) => {
      if (!appointmentDialog || !appointmentForm) return;
      appointmentForm.reset();
      appointmentForm.elements.appointment_id.value = appointment?._id || "";
      renderSlotGrid();
      if (appointmentTitle) {
        appointmentTitle.textContent = appointment ? "Change appointment" : "Share appointment slot";
      }
      if (appointmentSubmit) {
        appointmentSubmit.textContent = appointment ? "Request change" : "Share slot";
      }
      if (appointment?.start_at) {
        const start = new Date(appointment.start_at);
        const end = new Date(appointment.end_at);
        appointmentForm.elements.date.value = start.toISOString().slice(0, 10);
        appointmentForm.elements.mode.value = appointment.mode || "online";
        for (let h = start.getHours(); h < end.getHours(); h += 1) {
          slotGrid?.querySelector(`[data-slot-hour="${h}"]`)?.classList.add("selected");
        }
      } else {
        appointmentForm.elements.date.value = new Date().toISOString().slice(0, 10);
      }
      appointmentDialog.showModal?.();
    };

    const renderAppointments = (appointments) => {
      if (!appointmentStrip) return;
      appointmentStrip.innerHTML = "";
      if (!appointments.length) {
        appointmentStrip.hidden = true;
        return;
      }
      appointmentStrip.hidden = false;
      appointments.forEach((appointment) => {
        const card = document.createElement("article");
        card.className = "appointment-card";

        const header = document.createElement("header");
        const title = document.createElement("strong");
        title.textContent = appointment.label;
        const status = document.createElement("span");
        status.className = "badge";
        status.textContent = appointment.status.replace("_", " ");
        header.append(title, status);

        const meta = document.createElement("p");
        meta.className = "muted small";
        meta.textContent = `${appointment.mode} appointment with ${appointment.doctor_name}`;

        const footer = document.createElement("footer");
        const approvals = document.createElement("span");
        approvals.className = "small";
        approvals.textContent = `${appointment.approvals_count}/2 approvals`;
        footer.appendChild(approvals);

        if (!appointment.approved_by_me && appointment.status !== "booked") {
          const approve = document.createElement("button");
          approve.className = "btn primary";
          approve.type = "button";
          approve.textContent = "Approve";
          approve.addEventListener("click", async () => {
            const res = await fetch(`/api/appointments/${appointment._id}/approve`, { method: "POST" });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
              alert(data.error || "Could not approve appointment");
              return;
            }
            await loadCalendar();
          });
          footer.appendChild(approve);
        }

        const edit = document.createElement("button");
        edit.className = "icon-btn";
        edit.type = "button";
        edit.title = "Change appointment";
        edit.setAttribute("aria-label", "Change appointment");
        edit.textContent = "Edit";
        edit.addEventListener("click", () => openAppointmentDialog(appointment));
        footer.appendChild(edit);

        card.append(header, meta, footer);
        appointmentStrip.appendChild(card);
      });
    };

    const loadCalendar = async () => {
      if (!activeThreadId || !appointmentStrip) return;
      if (calendarDisabled) return;
      try {
        const res = await fetch(`/api/messages/${activeThreadId}/calendar`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          if (res.status === 400 || res.status === 403) {
            calendarDisabled = true;
            calendarState = null;
            appointmentStrip.hidden = true;
          }
          if (openAppointmentBtn) openAppointmentBtn.hidden = true;
          return;
        }
        calendarState = data;
        if (openAppointmentBtn) openAppointmentBtn.hidden = !data.can_propose;
        renderAppointments(data.appointments || []);
      } catch {
        // ignore
      }
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
          cache: "no-store",
        });
        if (!res.ok) return;
        const data = await res.json();
        const msgs = data.messages || [];
        setOtherPresence(Boolean(data.other_online));
        updateSeenReceipts(data.other_last_read_at || null);
        if (msgs.length) {
          appendMessages(msgs);
          await markRead();
        }
      } catch {
        // ignore
      }
    };

    const pingPresence = async () => {
      const payload = new FormData();
      if (activeThreadId) payload.append("thread_id", activeThreadId);
      try {
        const res = await fetch("/api/messages/presence", {
          method: "POST",
          body: payload,
          headers: { Accept: "application/json" },
        });
        if (!res.ok) return;
        const data = await res.json().catch(() => ({}));
        if (activeThreadId) {
          setOtherPresence(Boolean(data.other_online));
          updateSeenReceipts(data.other_last_read_at || null);
        }
      } catch {
        // ignore
      }
    };

    fetchUnread();
    pingPresence();
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
      setInterval(refreshThreads, 5000);
    }
    if (navBadge) {
      setInterval(fetchUnread, 5000);
    }
    setInterval(pingPresence, 8000);
    if (activeThreadId && messagesList) {
      const existing = Array.from(
        messagesList.querySelectorAll("[data-created-at]")
      );
      if (existing.length) {
        lastSeen = existing[existing.length - 1].dataset.createdAt || null;
      }
      markRead();
      setInterval(pollActiveConversation, 2500);
      loadCalendar();
      setInterval(loadCalendar, 15000);
    }

    const refreshPresenceNow = () => {
      pingPresence();
      if (activeThreadId && messagesList) {
        pollActiveConversation();
      } else if (threadsList) {
        refreshThreads();
      }
    };

    window.addEventListener("focus", refreshPresenceNow);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") {
        refreshPresenceNow();
      }
    });

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

    openAppointmentBtn?.addEventListener("click", () => openAppointmentDialog());

    appointmentForm?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!activeThreadId) return;
      const slots = selectedSlots();
      const date = appointmentForm.elements.date.value;
      const mode = appointmentForm.elements.mode.value;
      const appointmentId = appointmentForm.elements.appointment_id.value;
      const payload = { date, mode, slots };
      const url = appointmentId
        ? `/api/appointments/${appointmentId}/reschedule`
        : `/api/messages/${activeThreadId}/appointments`;
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert(data.error || "Could not save appointment");
          return;
        }
        appointmentDialog?.close?.();
        await loadCalendar();
        if (!appointmentId) {
          await pollActiveConversation();
        }
      } catch {
        alert("Could not save appointment");
      }
    });
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
    const assignInDetailsBtn = detailsDialog?.querySelector("[data-assign-doctor-modal]");
    const assignDoctorSelect = detailsDialog?.querySelector("[data-assign-doctor-select]");
    const assignDoctorToAdminBtn = detailsDialog?.querySelector("[data-assign-doctor-to-admin]");
    const adminUserDetailsDialog = document.getElementById("adminUserDetailsDialog");
    const adminUserDoctorsList = adminUserDetailsDialog?.querySelector("[data-admin-user-doctors-list]");

    const fillDetails = (menu) => {
      if (!detailsDialog) return;
      detailsDialog.querySelector("[data-admin-details-title]").textContent = menu.dataset.doctorName || "Doctor details";
      detailsDialog.querySelector("[data-admin-details-email]").textContent = menu.dataset.doctorEmail || "";
      detailsDialog.querySelector("[data-admin-details-phone]").textContent = menu.dataset.doctorPhone || "";
      detailsDialog.querySelector("[data-admin-details-specialization]").textContent = menu.dataset.doctorSpecialization || "";
      detailsDialog.querySelector("[data-admin-details-license]").textContent = menu.dataset.doctorLicense || "";
      detailsDialog.querySelector("[data-admin-details-city]").textContent = menu.dataset.doctorCity || "";
      detailsDialog.querySelector("[data-admin-details-pin]").textContent = menu.dataset.doctorPin || "";
      detailsDialog.querySelector("[data-admin-details-assigned-admin]").textContent = menu.dataset.doctorAssignedAdminName || "Unassigned";
      detailsDialog.querySelector("[data-admin-details-description]").textContent = (menu.dataset.doctorDescription || "").trim() || "No description";

      if (assignInDetailsBtn) {
        const assignedAdminId = menu.dataset.doctorAssignedAdminId || "";
        assignInDetailsBtn.dataset.assignDoctor = menu.dataset.doctorId || "";
        assignInDetailsBtn.hidden = Boolean(assignedAdminId);
        assignInDetailsBtn.disabled = false;
      }
      if (assignDoctorSelect) {
        assignDoctorSelect.value = menu.dataset.doctorAssignedAdminId || "";
      }
      if (assignDoctorToAdminBtn) {
        assignDoctorToAdminBtn.dataset.assignDoctor = menu.dataset.doctorId || "";
        assignDoctorToAdminBtn.disabled = false;
      }

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

    const loadAdminDoctorAssignments = async (menu) => {
      if (!adminUserDetailsDialog || !adminUserDoctorsList) return;
      adminUserDetailsDialog.querySelector("[data-admin-user-details-title]").textContent = menu.dataset.userName || "Admin details";
      adminUserDetailsDialog.querySelector("[data-admin-user-details-email]").textContent = menu.dataset.userEmail || "";
      adminUserDoctorsList.innerHTML = '<p class="muted">Loading doctors...</p>';
      adminUserDetailsDialog.showModal?.();
      try {
        const res = await fetch(`/api/admin/admins/${menu.dataset.userId}/doctors`, {
          headers: { Accept: "application/json" },
          cache: "no-store",
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          adminUserDoctorsList.innerHTML = `<p class="muted">${data.error || "Could not load doctors."}</p>`;
          return;
        }
        const doctors = data.doctors || [];
        if (!doctors.length) {
          adminUserDoctorsList.innerHTML = '<p class="muted">No doctors assigned to this admin.</p>';
          return;
        }
        adminUserDoctorsList.innerHTML = "";
        doctors.forEach((doctor) => {
          const row = document.createElement("div");
          row.className = "card";
          row.style.padding = "0.75rem";

          const title = document.createElement("strong");
          title.textContent = doctor.name;
          const meta = document.createElement("p");
          meta.className = "muted small";
          meta.textContent = [doctor.email, doctor.specialization].filter(Boolean).join(" · ");
          const action = document.createElement("button");
          action.type = "button";
          action.className = "btn secondary";
          action.textContent = "Remove";
          action.addEventListener("click", async () => {
            action.disabled = true;
            try {
              const removeRes = await fetch(`/api/admin/admins/${menu.dataset.userId}/doctors/${doctor._id}/remove`, {
                method: "POST",
                headers: { Accept: "application/json" },
              });
              const removeData = await removeRes.json().catch(() => ({}));
              if (!removeRes.ok) {
                alert(removeData.error || "Could not remove doctor");
                action.disabled = false;
                return;
              }
              row.remove();
              if (!adminUserDoctorsList.children.length) {
                adminUserDoctorsList.innerHTML = '<p class="muted">No doctors assigned to this admin.</p>';
              }
            } catch {
              alert("Could not remove doctor");
              action.disabled = false;
            }
          });
          row.append(title, meta, action);
          adminUserDoctorsList.appendChild(row);
        });
      } catch {
        adminUserDoctorsList.innerHTML = '<p class="muted">Could not load doctors.</p>';
      }
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

      menu.querySelector("[data-admin-user-view]")?.addEventListener("click", () => {
        menu.setAttribute("hidden", "");
        loadAdminDoctorAssignments(menu);
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

    assignDoctorToAdminBtn?.addEventListener("click", async () => {
      const doctorId = assignDoctorToAdminBtn.dataset.assignDoctor;
      const adminId = assignDoctorSelect?.value || "";
      if (!doctorId || !adminId) {
        alert("Select an admin first.");
        return;
      }
      assignDoctorToAdminBtn.disabled = true;
      const payload = new FormData();
      payload.append("admin_id", adminId);
      try {
        const res = await fetch(`/api/admin/doctors/${doctorId}/assign-to`, {
          method: "POST",
          body: payload,
          headers: { Accept: "application/json" },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert(data.error || "Could not assign doctor");
          assignDoctorToAdminBtn.disabled = false;
          return;
        }
        window.location.reload();
      } catch {
        alert("Could not assign doctor");
        assignDoctorToAdminBtn.disabled = false;
      }
    });
  };

  const initAdminDoctorAssignment = () => {
    document.querySelectorAll("[data-assign-doctor], [data-assign-doctor-modal]").forEach((button) => {
      button.addEventListener("click", async () => {
        const doctorId = button.dataset.assignDoctor;
        if (!doctorId) return;
        button.disabled = true;
        try {
          const res = await fetch(`/api/admin/doctors/${doctorId}/assign`, {
            method: "POST",
            headers: { Accept: "application/json" },
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            alert(data.error || "Could not assign doctor");
            button.disabled = false;
            return;
          }
          window.location.reload();
        } catch {
          alert("Could not assign doctor");
          button.disabled = false;
        }
      });
    });
  };

  const initAdminCalendar = () => {
    const root = document.querySelector("[data-admin-calendar]");
    if (!root) return;
    const list = root.querySelector("[data-admin-appointments]");
    const title = root.querySelector("[data-admin-calendar-title]");
    const refresh = root.querySelector("[data-admin-calendar-refresh]");
    const dialog = document.querySelector("[data-admin-appointment-dialog]");
    const form = document.querySelector("[data-admin-appointment-form]");
    const slotGrid = document.querySelector("[data-admin-slot-grid]");
    let activeDoctorId = "";
    let currentAppointments = [];

    const slotLabel = (hour) => {
      const formatHour = (h) => {
        const normalized = ((h % 24) + 24) % 24;
        const suffix = normalized >= 12 ? "PM" : "AM";
        const display = normalized % 12 || 12;
        return `${display} ${suffix}`;
      };
      return `${formatHour(hour)}-${formatHour(hour + 1)}`;
    };

    const renderSlots = () => {
      if (!slotGrid) return;
      slotGrid.innerHTML = "";
      for (let hour = 7; hour <= 21; hour += 1) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "slot-chip";
        btn.dataset.slotHour = String(hour);
        btn.textContent = slotLabel(hour);
        btn.addEventListener("click", () => btn.classList.toggle("selected"));
        slotGrid.appendChild(btn);
      }
    };

    const selectedSlots = () =>
      Array.from(slotGrid?.querySelectorAll(".slot-chip.selected") || [])
        .map((btn) => Number(btn.dataset.slotHour))
        .sort((a, b) => a - b);

    const openEdit = (appointment) => {
      if (!dialog || !form || !appointment) return;
      form.reset();
      renderSlots();
      form.elements.appointment_id.value = appointment._id;
      form.elements.mode.value = appointment.mode || "online";
      const start = new Date(appointment.start_at);
      const end = new Date(appointment.end_at);
      form.elements.date.value = start.toISOString().slice(0, 10);
      for (let h = start.getHours(); h < end.getHours(); h += 1) {
        slotGrid?.querySelector(`[data-slot-hour="${h}"]`)?.classList.add("selected");
      }
      dialog.showModal?.();
    };

    const render = (appointments) => {
      if (!list) return;
      list.innerHTML = "";
      if (!appointments.length) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "No appointments yet.";
        list.appendChild(empty);
        return;
      }
      appointments.forEach((appointment) => {
        const card = document.createElement("article");
        card.className = "appointment-card";
        const header = document.createElement("header");
        const name = document.createElement("strong");
        name.textContent = appointment.label;
        const status = document.createElement("span");
        status.className = "badge";
        status.textContent = appointment.status.replace("_", " ");
        header.append(name, status);
        const details = document.createElement("p");
        details.className = "muted small";
        details.textContent = `${appointment.doctor_name} with ${appointment.patient_name} (${appointment.mode})`;
        const footer = document.createElement("footer");
        const edit = document.createElement("button");
        edit.className = "icon-btn";
        edit.type = "button";
        edit.textContent = "Edit";
        edit.setAttribute("aria-label", "Change appointment");
        edit.addEventListener("click", () => openEdit(appointment));
        footer.appendChild(edit);
        card.append(header, details, footer);
        list.appendChild(card);
      });
    };

    const load = async () => {
      if (!list) return;
      list.innerHTML = '<p class="muted">Loading appointments...</p>';
      const url = new URL("/api/admin/calendar", window.location.origin);
      if (activeDoctorId) url.searchParams.set("doctor_id", activeDoctorId);
      try {
        const res = await fetch(url.toString(), { headers: { Accept: "application/json" } });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          list.innerHTML = "";
          const error = document.createElement("p");
          error.className = "alert error";
          error.textContent = data.error || "Could not load calendar";
          list.appendChild(error);
          return;
        }
        currentAppointments = data.appointments || [];
        render(currentAppointments);
      } catch {
        list.innerHTML = '<p class="alert error">Could not load calendar</p>';
      }
    };

    root.querySelectorAll("[data-admin-calendar-doctor]").forEach((button) => {
      button.addEventListener("click", () => {
        activeDoctorId = button.dataset.adminCalendarDoctor || "";
        if (title) title.textContent = button.querySelector("strong")?.textContent || "Doctor appointments";
        load();
      });
    });
    refresh?.addEventListener("click", load);
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const appointmentId = form.elements.appointment_id.value;
      if (!appointmentId) return;
      const payload = {
        date: form.elements.date.value,
        mode: form.elements.mode.value,
        slots: selectedSlots(),
      };
      try {
        const res = await fetch(`/api/appointments/${appointmentId}/reschedule`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          alert(data.error || "Could not change appointment");
          return;
        }
        dialog?.close?.();
        load();
      } catch {
        alert("Could not change appointment");
      }
    });
    load();
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
  initPresenceHeartbeat();
  initDescriptionEditor();
  initDoctorCards();
  initAdminKebabMenus();
  initAdminDoctorAssignment();
  initAdminCalendar();
  initMessaging();
});
