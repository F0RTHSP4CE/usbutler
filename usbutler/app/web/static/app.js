(() => {
  const scanBtn = document.querySelector("#scan-card-btn");
  const scanStatus = document.querySelector("#scan-status");
  const identifierInput = document.querySelector("#identifier");
  const identifierToggleBtn = document.querySelector(".toggle-identifier");
  const identifierTypeLabel = document.querySelector("#identifier-type");
  const cardMetaContainer = document.querySelector("#card-meta");
  const existingUserAlert = document.querySelector("#existing-user-alert");
  const addUserForm = document.querySelector("#add-user-form");
  const usersTableBody = document.querySelector("#users-table-body");
  const readerControlCard = document.querySelector("#reader-control-card");
  const claimReaderBtn = document.querySelector("#claim-reader-btn");
  const releaseReaderBtn = document.querySelector("#release-reader-btn");
  const readerStatusMessage = document.querySelector("#reader-status-message");
  const readerOwnerBadge = document.querySelector("#reader-owner-badge");
  const readerEnabled = document.body?.dataset?.readerEnabled === "true";

  const assignNewRadio = document.querySelector("#assign-new");
  const assignExistingRadio = document.querySelector("#assign-existing");
  const newUserFields = document.querySelector("#new-user-fields");
  const accessLevelField = document.querySelector("#access-level-field");
  const existingUserWrapper = document.querySelector("#existing-user-select-wrapper");
  const existingUserSelect = document.querySelector("#existing_user");
  const submitBtn = document.querySelector("#submit-btn");

  let cachedUsers = [];
  let latestScan = null;
  let inputMasked = true;
  let currentReaderState = null;
  let isScanning = false;

  const maskValue = (value = "") =>
    value.length <= 4 ? value : `****${value.slice(-4)}`;

  const formatExpiry = (expiry) => {
    if (!expiry) return null;
    if (typeof expiry === "string" && expiry.includes("/")) {
      return expiry;
    }
    const digits = String(expiry).replace(/\D+/g, "");
    if (digits.length === 4) {
      return `${digits.slice(2)}/${digits.slice(0, 2)}`;
    }
    return String(expiry);
  };

  const renderMetadataDetails = (metadata) => {
    if (!metadata || Object.keys(metadata).length === 0) {
      return "";
    }

    const items = [];
    if (metadata.issuer) {
      items.push(`<div><span class="text-muted">Issuer:</span> ${metadata.issuer}</div>`);
    }
    const expiry = metadata.expiry
    if (expiry) {
      items.push(`<div><span class="text-muted">Expiry:</span> ${expiry}</div>`);
    }
    if (metadata.card_type) {
      items.push(`<div><span class="text-muted">Card type:</span> ${metadata.card_type}</div>`);
    }
    if (metadata.tag_type) {
      items.push(`<div><span class="text-muted">Tag type:</span> ${metadata.tag_type}</div>`);
    }
    if (metadata.atr_hex) {
      items.push(`<div><span class="text-muted">ATR:</span> <code>${metadata.atr_hex}</code></div>`);
    }
    if (Array.isArray(metadata.atr_summary) && metadata.atr_summary.length) {
      const summaryItems = metadata.atr_summary
        .map((line) => `<li>${line}</li>`)
        .join("");
      items.push(
        `<div><span class="text-muted">ATR summary:</span><ul class="small mb-0">${summaryItems}</ul></div>`
      );
    }

    if (!items.length) {
      return "";
    }

    return `
      <details class="mt-2">
        <summary class="btn btn-link btn-sm px-0">Show EMV details</summary>
        <div class="small text-muted d-flex flex-column gap-1 mt-2">${items.join("")}</div>
      </details>
    `;
  };

  const isReaderOwnedByWeb = () => currentReaderState?.owner === "web";

  const canScanWithReader = () => readerEnabled && isReaderOwnedByWeb();

  const formatOwnerLabel = (owner) => {
    if (!owner) return "Unknown";
    if (owner === "web") return "Web UI";
    if (owner === "door") return "Door service";
    return owner[0]?.toUpperCase() + owner.slice(1);
  };


  const updateScanButtonState = () => {
    if (!scanBtn) return;
    const spinner = scanBtn.querySelector(".spinner-border");
    const label = scanBtn.querySelector(".default-label");
    if (isScanning) {
      scanBtn.disabled = true;
      spinner?.classList.remove("d-none");
      if (label) label.textContent = "Scanning…";
      return;
    }

    spinner?.classList.add("d-none");
    if (label) label.textContent = "Scan card";
    scanBtn.disabled = !canScanWithReader();
  };

  const updateReaderControlUI = (stateOverride = null) => {
    if (stateOverride) {
      currentReaderState = stateOverride;
    }
    if (!readerControlCard) {
      updateScanButtonState();
      return;
    }

    const state = currentReaderState;
    const owner = state?.owner || "door";

    if (readerOwnerBadge) {
      readerOwnerBadge.textContent = formatOwnerLabel(owner);
      readerOwnerBadge.classList.remove("bg-secondary", "bg-success", "bg-primary", "bg-warning");
      const badgeClass = owner === "web" ? "bg-success" : owner === "door" ? "bg-primary" : "bg-warning";
      readerOwnerBadge.classList.add(badgeClass);
    }

    if (!readerEnabled) {
      readerStatusMessage?.classList.remove("text-danger");
      if (readerStatusMessage) {
        readerStatusMessage.textContent =
          "Web access to the reader is disabled. Enable USBUTLER_WEB_ENABLE_READER to use it here.";
      }
      if (claimReaderBtn) claimReaderBtn.disabled = true;
      if (releaseReaderBtn) releaseReaderBtn.disabled = true;
    } else {
      readerStatusMessage?.classList.remove("text-danger");
      if (readerStatusMessage) {
        const baseMessage = owner === "web"
          ? "Web UI currently controls the reader. You can scan cards from this page."
          : owner === "door"
            ? "Door service currently controls the reader. Unlock it to pause the door service and scan here."
            : `Reader reserved by ${formatOwnerLabel(owner)}.`;
        readerStatusMessage.textContent = baseMessage;
      }
      if (claimReaderBtn) {
        claimReaderBtn.disabled = owner === "web";
      }
      if (releaseReaderBtn) {
        releaseReaderBtn.disabled = owner === "door";
      }
    }

    updateScanButtonState();
  };

  const refreshReaderState = async () => {
    if (!readerControlCard) {
      updateScanButtonState();
      return;
    }
    try {
      const response = await fetch("/api/reader");
      if (!response.ok) {
        throw new Error("Failed to fetch reader state");
      }
      const data = await response.json();
      if (data.success && data.state) {
        updateReaderControlUI(data.state);
      }
    } catch (error) {
      console.error(error);
      if (readerStatusMessage) {
        readerStatusMessage.textContent = "Unable to check reader state.";
        readerStatusMessage.classList.add("text-danger");
      }
    }
  };

  const runReaderAction = async (endpoint, button) => {
    if (!readerEnabled) {
      return;
    }
    const originalText = button?.textContent;
    if (button) {
      button.disabled = true;
      button.textContent = `${originalText}…`;
    }
    let success = false;
    try {
      const response = await fetch(endpoint, { method: "POST" });
      const data = await response.json();
      if (response.ok && data.success) {
        success = true;
        if (data.state) {
          updateReaderControlUI(data.state);
        } else {
          await refreshReaderState();
        }
        if (endpoint.endsWith("/claim") && readerStatusMessage) {
          readerStatusMessage.textContent = "Reader unlocked for the web UI.";
          readerStatusMessage.classList.remove("text-danger");
        }
        if (endpoint.endsWith("/release") && readerStatusMessage) {
          readerStatusMessage.textContent = "Reader returned to the door service.";
          readerStatusMessage.classList.remove("text-danger");
        }
        updateScanButtonState();
        if (endpoint.endsWith("/claim") && scanStatus) {
          scanStatus.textContent = "Reader ready. Tap a card to begin.";
        }
        if (endpoint.endsWith("/release") && scanStatus) {
          scanStatus.textContent = "Reader controlled by door service.";
        }
      } else if (readerStatusMessage) {
        readerStatusMessage.textContent = data?.message || "Unable to update reader state.";
        readerStatusMessage.classList.add("text-danger");
      }
    } catch (error) {
      console.error(error);
      if (readerStatusMessage) {
        readerStatusMessage.textContent = "Error communicating with reader control.";
        readerStatusMessage.classList.add("text-danger");
      }
    } finally {
      if (button) {
        button.textContent = originalText;
        if (!success) {
          button.disabled = false;
        }
      }
      if (!success) {
        updateScanButtonState();
      }
    }
  };

  const initializeReaderStateFromDataset = () => {
    if (!readerControlCard) {
      updateScanButtonState();
      return;
    }
    const initial = readerControlCard.dataset.initialReaderState;
    if (initial) {
      try {
        currentReaderState = JSON.parse(initial);
      } catch (error) {
        console.error("Failed to parse initial reader state", error);
      }
    }
    updateReaderControlUI();
    if (scanStatus) {
      const currentText = scanStatus.textContent.trim();
      if (!readerEnabled) {
        scanStatus.textContent = "Reader access is disabled for this server.";
      } else if (!isReaderOwnedByWeb() && (!currentText || currentText === "Waiting for scan…")) {
        scanStatus.textContent = "Reader is controlled by the door service. Unlock it above to scan.";
      }
    }
  };

  const buildMetadataPayload = (scan) => {
    if (!scan || !scan.metadata) {
      return null;
    }
    const allowed = [
      "issuer",
      "expiry",
      "card_type",
      "tag_type",
      "atr_hex",
      "atr_hex_compact",
      "atr_summary",
    ];
    const result = {};
    allowed.forEach((key) => {
      if (key in scan.metadata && scan.metadata[key] !== undefined && scan.metadata[key] !== null) {
        result[key] = scan.metadata[key];
      }
    });
    return Object.keys(result).length ? result : null;
  };

  const resolveSensitiveContainer = (button) => {
    if (!button) return null;
    const direct = button.closest(".sensitive");
    if (direct) return direct;
    const wrapper = button.closest(".identifier-entry");
    return wrapper?.querySelector(".sensitive") ?? null;
  };

  const setScanLoading = (loading) => {
    isScanning = loading;
    updateScanButtonState();
  };

  const toggleSensitiveDisplay = (container) => {
    const masked = container.querySelector(".masked");
    const full = container.querySelector(".full");
    if (!masked || !full) {
      return false;
    }
    const showingMasked = !masked.classList.contains("d-none");
    if (showingMasked) {
      masked.classList.add("d-none");
      full.classList.remove("d-none");
      return true;
    }
    masked.classList.remove("d-none");
    full.classList.add("d-none");
    return false;
  };

  const updateCardMeta = (payload) => {
    if (!cardMetaContainer) return;
    const body = cardMetaContainer.querySelector(".card-body");
    if (!body) return;

    if (!payload) {
      body.innerHTML = '<div class="py-2 small text-muted">Scan a card to view details.</div>';
      return;
    }

    const rows = [];
    if (payload.identifier_type) {
      rows.push(`<div>Identifier type: <strong>${payload.identifier_type}</strong></div>`);
    }
    if (payload.tag_type) {
      rows.push(`<div>Tag type: ${payload.tag_type}</div>`);
    }
    if (payload.card_type) {
      rows.push(`<div>Card type: ${payload.card_type}</div>`);
    }
    if (payload.uid) {
      rows.push(`
        <div class="sensitive">
          UID: <span class="masked text-monospace">${maskValue(payload.uid)}</span>
          <span class="full text-monospace d-none">${payload.uid}</span>
          <button class="btn btn-link btn-sm px-1 toggle-sensitive" type="button">Show</button>
        </div>
      `);
    }
    if (payload.pan) {
      rows.push(`
        <div class="sensitive">
          PAN: <span class="masked text-monospace">${maskValue(payload.pan)}</span>
          <span class="full text-monospace d-none">${payload.pan}</span>
          <button class="btn btn-link btn-sm px-1 toggle-sensitive" type="button">Show</button>
        </div>
      `);
    }
    if (payload.tokenized) {
      rows.push("<div class=\"text-warning\">Tokenized/HCE: yes</div>");
    }

    const metadataView = {
      ...(payload.metadata || {}),
    };
    if (!metadataView.issuer && payload.issuer) {
      metadataView.issuer = payload.issuer;
    }
    if (!metadataView.expiry && payload.expiry) {
      metadataView.expiry = payload.expiry;
    }
    if (!metadataView.card_type && payload.card_type) {
      metadataView.card_type = payload.card_type;
    }
    if (!metadataView.tag_type && payload.tag_type) {
      metadataView.tag_type = payload.tag_type;
    }
    if (!metadataView.atr_hex && payload.atr_hex) {
      metadataView.atr_hex = payload.atr_hex;
    }
    if (!metadataView.atr_summary && payload.atr_summary) {
      metadataView.atr_summary = payload.atr_summary;
    }

    const metadataSection = renderMetadataDetails(metadataView);

    body.innerHTML = (rows.join("\n") || '<div class="py-2 small text-muted">No additional data.</div>') + metadataSection;
  };

  const renderUsers = (users) => {
    cachedUsers = users;
    if (!usersTableBody) return;
    if (!users.length) {
      usersTableBody.innerHTML = `
        <tr>
          <td colspan="4" class="text-center py-4 text-muted">No users registered yet.</td>
        </tr>`;
      return;
    }

    const rows = users
      .map((user) => {
        const identifiersMarkup = user.identifiers
          .map((identifier) => {
            const removeBtn = user.identifiers.length > 1
              ? `<button class="btn btn-link btn-sm px-1 text-danger remove-identifier" type="button" data-user-id="${user.user_id}" data-identifier="${identifier.value}">Remove</button>`
              : "";
            return `
              <div class="identifier-entry mb-2" data-identifier="${identifier.value}">
                <span class="badge bg-info-subtle text-dark me-2">${identifier.type}</span>
                <span class="sensitive text-monospace">
                  <span class="masked">${identifier.masked}</span>
                  <span class="full d-none">${identifier.value}</span>
                </span>
                <button class="btn btn-link btn-sm px-1 toggle-sensitive" type="button">Show</button>
                ${removeBtn}
              </div>
            `;
          })
          .join("\n");

        const statusButton = user.active
          ? `<button class="btn btn-outline-secondary pause-user" type="button" data-user-id="${user.user_id}">Pause</button>`
          : `<button class="btn btn-outline-primary resume-user" type="button" data-user-id="${user.user_id}">Resume</button>`;

        return `
          <tr data-user-id="${user.user_id}" class="${user.active ? "" : "table-secondary"}">
            <td>
              <div class="fw-semibold">${user.name}</div>
              <div class="small text-muted text-uppercase">${user.access_level}</div>
            </td>
            <td>${identifiersMarkup}</td>
            <td class="text-capitalize">${user.access_level}</td>
            <td class="text-end">
              <div class="btn-group btn-group-sm" role="group">
                ${statusButton}
                <button class="btn btn-outline-danger remove-user" type="button" data-user-id="${user.user_id}">Remove</button>
              </div>
            </td>
          </tr>
        `;
      })
      .join("\n");

    usersTableBody.innerHTML = rows;
  };

  const populateExistingUsers = () => {
    if (!existingUserSelect) return;
    const options = ["<option value=''>Choose a user…</option>"];
    const sorted = [...cachedUsers].sort((a, b) => a.name.localeCompare(b.name));
    sorted.forEach((user) => {
      options.push(`<option value="${user.user_id}">${user.name} (${user.access_level})</option>`);
    });
    existingUserSelect.innerHTML = options.join("\n");
  };

  const setAssignMode = (mode) => {
    const isNew = mode === "new";
    if (isNew) {
      newUserFields?.classList.remove("d-none");
      accessLevelField?.classList.remove("d-none");
      existingUserWrapper?.classList.add("d-none");
      if (existingUserSelect) {
        existingUserSelect.disabled = true;
      }
    } else {
      newUserFields?.classList.add("d-none");
      accessLevelField?.classList.add("d-none");
      existingUserWrapper?.classList.remove("d-none");
      if (existingUserSelect) {
        existingUserSelect.disabled = false;
      }
    }
    if (submitBtn) {
      submitBtn.textContent = isNew ? "Create user" : "Add card";
    }
    updateSubmitState();
  };

  const getAssignMode = () =>
    assignExistingRadio?.checked ? "existing" : "new";

  const updateSubmitState = () => {
    if (!submitBtn) return;
    const hasIdentifier = Boolean(identifierInput?.value);
    let canSubmit = hasIdentifier;

    if (existingUserAlert && !existingUserAlert.classList.contains("d-none")) {
      canSubmit = false;
    }

    if (getAssignMode() === "new") {
      const nameField = document.querySelector("#name");
      canSubmit = canSubmit && Boolean(nameField?.value.trim());
    } else {
      canSubmit = canSubmit && Boolean(existingUserSelect?.value);
    }

    submitBtn.disabled = !canSubmit;
  };

  const clearScanState = () => {
    latestScan = null;
    inputMasked = true;
    identifierInput.value = "";
    identifierInput.type = "password";
    identifierToggleBtn.textContent = "Show";
    identifierToggleBtn.disabled = true;
    identifierTypeLabel.textContent = "Identifier type: —";
    updateCardMeta(null);
    if (existingUserAlert) {
      existingUserAlert.classList.add("d-none");
      existingUserAlert.textContent = "";
    }
    if (scanStatus) {
      scanStatus.textContent = "Waiting for scan…";
    }
    updateSubmitState();
  };

  const refreshUsers = async () => {
    const response = await fetch("/api/users");
    if (!response.ok) {
      return;
    }
    const data = await response.json();
    if (!data.success) {
      return;
    }
    if (data.reader_state) {
      updateReaderControlUI(data.reader_state);
    }
    renderUsers(data.users || []);
    populateExistingUsers();
  };

  const handlePauseUser = async (userId) => {
    const response = await fetch(`/api/users/${encodeURIComponent(userId)}/pause`, {
      method: "POST",
    });
    if (response.ok) {
      await refreshUsers();
    }
  };

  const handleResumeUser = async (userId) => {
    const response = await fetch(`/api/users/${encodeURIComponent(userId)}/resume`, {
      method: "POST",
    });
    if (response.ok) {
      await refreshUsers();
    }
  };

  const handleRemoveUser = async (userId) => {
    if (!confirm("Remove this user and all their cards?")) {
      return;
    }
    const response = await fetch(`/api/users/${encodeURIComponent(userId)}`, {
      method: "DELETE",
    });
    if (response.ok) {
      await refreshUsers();
    }
  };

  const handleRemoveIdentifier = async (userId, identifier) => {
    if (!confirm("Remove this card from the user?")) {
      return;
    }
    const response = await fetch(
      `/api/users/${encodeURIComponent(userId)}/identifiers/${encodeURIComponent(identifier)}`,
      {
        method: "DELETE",
      },
    );
    if (response.ok) {
      await refreshUsers();
    }
  };


  identifierToggleBtn?.addEventListener("click", () => {
    if (!identifierInput.value) {
      return;
    }
    inputMasked = !inputMasked;
    identifierInput.type = inputMasked ? "password" : "text";
    identifierToggleBtn.textContent = inputMasked ? "Show" : "Hide";
  });

  assignNewRadio?.addEventListener("change", () => setAssignMode("new"));
  assignExistingRadio?.addEventListener("change", () => setAssignMode("existing"));
  existingUserSelect?.addEventListener("change", updateSubmitState);
  document.querySelector("#name")?.addEventListener("input", updateSubmitState);

  cardMetaContainer?.addEventListener("click", (event) => {
    const button = event.target.closest(".toggle-sensitive");
    if (!button) return;
    const container = resolveSensitiveContainer(button);
    if (!container) return;
    const showingFull = toggleSensitiveDisplay(container);
    button.textContent = showingFull ? "Hide" : "Show";
  });

  usersTableBody?.addEventListener("click", async (event) => {
    const button = event.target.closest("button");
    if (!button) return;

    if (button.classList.contains("toggle-sensitive")) {
      const container = resolveSensitiveContainer(button);
      if (!container) return;
      const showingFull = toggleSensitiveDisplay(container);
      button.textContent = showingFull ? "Hide" : "Show";
      return;
    }

    const userId = button.dataset.userId;
    const identifier = button.dataset.identifier;

    if (button.classList.contains("toggle-user") && userId) {
      const row = button.closest("tr");
      const isInactive = row?.classList.contains("table-secondary");
      if (isInactive) {
        await handleResumeUser(userId);
      } else {
        await handlePauseUser(userId);
      }
      return;
    }
    if (button.classList.contains("pause-user") && userId) {
      await handlePauseUser(userId);
      return;
    }
    if (button.classList.contains("resume-user") && userId) {
      await handleResumeUser(userId);
      return;
    }
    if (button.classList.contains("remove-user") && userId) {
      await handleRemoveUser(userId);
      return;
    }
    if (button.classList.contains("remove-identifier") && userId && identifier) {
      await handleRemoveIdentifier(userId, identifier);
      return;
    }
  });

  claimReaderBtn?.addEventListener("click", async () => {
    await runReaderAction("/api/reader/claim", claimReaderBtn);
  });

  releaseReaderBtn?.addEventListener("click", async () => {
    await runReaderAction("/api/reader/release", releaseReaderBtn);
  });

  scanBtn?.addEventListener("click", async () => {
    if (!readerEnabled) {
      if (scanStatus) {
        scanStatus.textContent = "Reader access is disabled for this server.";
      }
      return;
    }
    if (!isReaderOwnedByWeb()) {
      if (scanStatus) {
        scanStatus.textContent = "Unlock the reader above before scanning.";
      }
      return;
    }
    setScanLoading(true);
    scanStatus.textContent = "Waiting for card…";
    updateCardMeta(null);
    try {
      const response = await fetch("/api/scan-card", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ timeout: 15 }),
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        const message = data?.message || "Unable to read card.";
        scanStatus.textContent = message;
        return;
      }

      latestScan = data;
      identifierInput.value = data.identifier;
      identifierToggleBtn.disabled = false;
      inputMasked = true;
      identifierInput.type = "password";
      identifierToggleBtn.textContent = "Show";
      identifierTypeLabel.textContent = `Identifier type: ${data.identifier_type || "—"}`;
      scanStatus.textContent = `Card captured (${data.identifier_type || "identifier"})`;
      updateCardMeta(data);
      if (data.already_registered) {
        if (existingUserAlert) {
          const name = data.existing_user?.name || "another user";
          existingUserAlert.textContent = `This card is already assigned to ${name}.`;
          existingUserAlert.classList.remove("d-none");
        }
      } else if (existingUserAlert) {
        existingUserAlert.classList.add("d-none");
        existingUserAlert.textContent = "";
      }

      updateSubmitState();
      const mode = getAssignMode();
      if (mode === "existing" && existingUserSelect) {
        existingUserSelect.focus();
      } else {
        document.querySelector("#name")?.focus();
      }
    } catch (error) {
      scanStatus.textContent = "Error communicating with reader.";
      console.error(error);
    } finally {
      setScanLoading(false);
    }
  });

  addUserForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!identifierInput.value) {
      scanStatus.textContent = "Please scan a card before submitting.";
      return;
    }
    if (existingUserAlert && !existingUserAlert.classList.contains("d-none")) {
      scanStatus.textContent = "Resolve duplicate card before continuing.";
      return;
    }

    const mode = getAssignMode();
    const defaultLabel = mode === "new" ? "Create user" : "Add card";
    const payload = {
      identifier: identifierInput.value,
      identifier_type: latestScan?.identifier_type || "UID",
    };

    if (mode === "new") {
      const nameField = document.querySelector("#name");
      payload.name = nameField?.value?.trim();
      payload.access_level = document.querySelector("#access_level")?.value || "user";
      if (!payload.name) {
        scanStatus.textContent = "Name is required.";
        return;
      }
    } else {
      const userId = existingUserSelect?.value;
      if (!userId) {
        scanStatus.textContent = "Select a user to attach this card.";
        return;
      }
      payload.user_id = userId;
    }

    const metadataPayload = buildMetadataPayload(latestScan);
    if (metadataPayload) {
      payload.metadata = metadataPayload;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Saving…";

    try {
      const response = await fetch("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (response.ok && data.success) {
        addUserForm.reset();
        clearScanState();
        setAssignMode(getAssignMode());
        scanStatus.textContent = mode === "new" ? "User created and card assigned." : "Card added to user.";
        await refreshUsers();
      } else {
        const message = data?.error || "Failed to save.";
        scanStatus.textContent = message;
      }
    } catch (error) {
      scanStatus.textContent = "Error saving user.";
      console.error(error);
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = defaultLabel;
    }
  });

  initializeReaderStateFromDataset();
  refreshUsers();
  setAssignMode(getAssignMode());
  updateSubmitState();
  if (readerControlCard) {
    setInterval(refreshReaderState, 5000);
  }
})();
