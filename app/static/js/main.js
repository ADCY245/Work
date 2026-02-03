document.addEventListener("DOMContentLoaded", () => {
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
});
