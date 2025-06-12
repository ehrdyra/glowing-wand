document.addEventListener("DOMContentLoaded", () => {
  console.log("AnsiUp type:", typeof AnsiUp); // Debug AnsiUp loading

  // Define the base URL for API calls
  // When deployed via Ngrok, requests should be relative to the current origin
  const BASE_API_URL = "";

  const navLinks = document.querySelectorAll(".main-nav a");
  const contentSections = document.querySelectorAll(".content-section");
  const machineListDiv = document.getElementById("machine-list");
  const newMachineBtn = document.querySelector(".new-machine-btn");
  const newMachineModal = document.getElementById("new-machine-modal");
  const closeModalBtn = newMachineModal.querySelector(".close-button"); // For new machine modal - Changed selector
  const dockerImageInput = document.getElementById("docker-image");
  const dockerImageTagsSelect = document.getElementById("docker-image-tags");
  const newMachineForm = document.getElementById("new-machine-form"); // Moved declaration
  const createMachineBtn = document.querySelector(".create-machine-btn"); // Moved declaration

  const machineDetailsSection = document.getElementById(
    "machine-details-section"
  );
  const machineDetailsTitle = document.getElementById("machine-details-title");
  const machineLogsPre = document.getElementById("machine-logs");
  const messageArea = document.getElementById("message-area"); // New element
  let currentMachineId = null; // To store the ID of the currently viewed machine

  let currentUsageInterval = null; // Global variable to hold the setInterval for usage
  let currentLogsAbortController = null; // Global variable to hold the AbortController for logs

  // Chart instances
  let cpuChart = null;
  let ramChart = null;
  let netIoChart = null;

  // Function to destroy existing charts
  const destroyCharts = () => {
    if (cpuChart) {
      cpuChart.destroy();
      cpuChart = null;
    }
    if (ramChart) {
      ramChart.destroy();
      ramChart = null;
    }
    if (netIoChart) {
      netIoChart.destroy();
      netIoChart = null;
    }
  };

  // Function to display messages
  const showMessage = (message, type = "info") => {
    const messageItem = document.createElement("div");
    messageItem.classList.add("message-item", type);
    messageItem.textContent = message;
    messageArea.appendChild(messageItem);

    // Remove message after 4 seconds
    setTimeout(() => {
      messageItem.remove();
    }, 4000);
  };

  // Settings tab elements
  const buildCommandInput = document.getElementById("build-command");
  const installCommandInput = document.getElementById("install-command");
  const runCommandInput = document.getElementById("run-command");
  const forwardingPortInput = document.getElementById("forwarding-port");
  const uniquePathInput = document.getElementById("unique-path");
  const saveSettingsBtn = document.getElementById("save-settings-btn");

  // Validation message elements
  const forwardingPortValidationMessage = document.createElement("span");
  forwardingPortValidationMessage.classList.add("validation-message");
  forwardingPortInput.parentNode.appendChild(forwardingPortValidationMessage);

  const uniquePathAvailabilityMessage = document.createElement("span");
  uniquePathAvailabilityMessage.classList.add("validation-message");
  uniquePathInput.parentNode.appendChild(uniquePathAvailabilityMessage);

  let isForwardingPortValid = true;
  let isUniquePathAvailable = true; // Assume available until checked or if empty
  let originalUniquePath = ""; // To store the unique path loaded from settings

  // File Manager elements
  const dropZone = document.getElementById("drop-zone");
  const browseFilesBtn = document.getElementById("browse-files-btn");
  const fileUploadInput = document.getElementById("file-upload-input"); // Updated ID
  const gitRepoUrlInput = document.getElementById("git-repo-url");
  const gitCloneBtn = document.getElementById("git-clone-btn");
  const fileListUl = document.getElementById("file-list");
  const currentFilePathSpan = document.getElementById("current-file-path");
  let currentFilePath = "/"; // Track current path in file manager
  let currentEditingFilePath = null; // To store the full path of the file being edited

  // File Editor Modal elements
  const fileEditorModal = document.getElementById("file-editor-modal");
  const closeFileEditorModalBtn = document.getElementById("close-file-editor-modal");
  const editingFilePathSpan = document.getElementById("editing-file-path");
  const fileEditorTextarea = document.getElementById("file-editor-textarea");
  const saveFileContentBtn = document.getElementById("save-file-content-btn");
  const cancelFileContentBtn = document.getElementById("cancel-file-content-btn");


  const fetchAndRenderMachines = async () => {
    machineListDiv.innerHTML = "<p>Loading machine data...</p>";
    try {
      const response = await fetch(`${BASE_API_URL}/machines`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const machines = await response.json();
      renderMachines(machines);
    } catch (error) {
      console.error("Error fetching machine data:", error);
      machineListDiv.innerHTML =
        "<p>Failed to load machine data. Please ensure the backend is running.</p>";
    }
  };

  const renderMachines = (machines) => {
    if (machines.length === 0) {
      machineListDiv.innerHTML =
        "<p>No machines created yet. Click <strong>+ New Machine</strong> to get started.</p>";
      return;
    }

    machineListDiv.innerHTML = ""; // Clear loading message

    machines.forEach((machine) => {
      const machineItem = document.createElement("div");
      machineItem.classList.add("machine-item");

      let statusClass;
      let displayStatus = machine.status; // Default to actual status
      let buttonIcon;
      let isButtonDisabled = false;

      const imageBaseName = machine.docker_image
        ? machine.docker_image.split(":")[0].toLowerCase()
        : "default";
      const imageSrc = `/static/image/${imageBaseName}.svg`;
      if (machine.status === "Stopped" || machine.status === "Exited") {
        statusClass = "status-stopped";
        displayStatus = "Stopped"; // Standardize display for these states
        buttonIcon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>`; // Play icon
      } else if (
        machine.status === "Starting" ||
        machine.status === "Stopping"
      ) {
        statusClass = "status-pending"; // New class for pending states
        buttonIcon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>`; // Spinner icon
        isButtonDisabled = true;
        // Disable all buttons within the machine-actions div when in pending state
        machineItem
          .querySelectorAll(".machine-actions button")
          .forEach((button) => {
            button.disabled = true;
          });
      } else if (machine.status === "Running") {
        statusClass = "status-running";
        buttonIcon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><rect x="6" y="6" width="12" height="12"></rect></svg>`; // Stop icon
      } else {
        statusClass = "status-unknown"; // Fallback for unexpected statuses
        buttonIcon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>`; // Info icon
        isButtonDisabled = true;
      }

      // Determine the button's visual class (run-button or stop-button)
      const buttonVisualClass =
        machine.status === "Running" ? "stop-button" : "run-button";

      machineItem.innerHTML = `
                <div class="machine-header">
                    <div class="machine-info-group">
                        <div class="machine-logo-wrapper">
                            <img src="${imageSrc}" alt="${
        machine.name
      } Logo" class="machine-logo" onerror="this.onerror=null;this.src='/static/image/default.svg';" />
                        </div>
                        <h3>${machine.name}</h3>
                    </div>
                    <div class="machine-actions">
                        <button class="icon-button run-stop-button ${buttonVisualClass}" data-id="${
        machine.id
      }" ${isButtonDisabled ? "disabled" : ""}>
                            ${buttonIcon}
                        </button>
                        <button class="icon-button settings-button" data-id="${
                          machine.id
                        }">
                            <!-- Settings icon (SVG) -->
                            <svg width="256px" height="256px" viewBox="0 0 24.00 24.00" fill="none" xmlns="http://www.w3.org/2000/svg" transform="rotate(0)matrix(1, 0, 0, 1, 0, 0)"><g id="SVGRepo_bgCarrier" stroke-width="0"></g><g id="SVGRepo_tracerCarrier" stroke-linecap="round" stroke-linejoin="round" stroke="#CCCCCC" stroke-width="0.3"></g><g id="SVGRepo_iconCarrier"> <path d="M7.84308 3.80211C9.8718 2.6007 10.8862 2 12 2C13.1138 2 14.1282 2.6007 16.1569 3.80211L16.8431 4.20846C18.8718 5.40987 19.8862 6.01057 20.4431 7C21 7.98943 21 9.19084 21 11.5937V12.4063C21 14.8092 21 16.0106 20.4431 17C19.8862 17.9894 18.8718 18.5901 16.8431 19.7915L16.1569 20.1979C14.1282 21.3993 13.1138 22 12 22C10.8862 22 9.8718 21.3993 7.84308 20.1979L7.15692 19.7915C5.1282 18.5901 4.11384 17.9894 3.55692 17C4.11384 6.01057 5.1282 5.40987 7.15692 4.20846L7.84308 3.80211Z" stroke="currentColor" stroke-width="1.5"></path> <circle cx="12" cy="12" r="3" stroke="currentColor" stroke-width="1.5"></circle> </g></svg>
                        </button>
                        <button class="icon-button delete-button" data-id="${
                          machine.id
                        }">
                            <!-- Trash icon (SVG) -->
                            <svg viewBox="0 0 24 24" width="16" height="16" stroke="#979797" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                        </button>
                    </div>
                </div>
                <p>Instance ID: <code>${machine.id}</code></p>
                <p>RAM: ${machine.ram}</p>
                <p>Core: ${machine.core}</p>
                <p>Status: <span class="${statusClass}">${displayStatus}</span> for ${
        machine.uptime
      }</p>
            `;
      machineListDiv.appendChild(machineItem);

      // Add event listeners for the new buttons
      const runStopButton = machineItem.querySelector(".run-stop-button"); // Changed selector
      const settingsButton = machineItem.querySelector(".settings-button");
      const deleteButton = machineItem.querySelector(".delete-button");

      // Attach event listeners for the new buttons
      // runStopButton is conditionally enabled/disabled in HTML, and its listener is conditional
      if (!isButtonDisabled) {
        runStopButton.addEventListener("click", async () => {
          // Changed variable name
          if (!machine.id) {
            showMessage("Machine ID is missing.", "error");
            return;
          }

          const action = machine.status === "Running" ? "stop" : "start"; // Determine action
          const endpoint = `${BASE_API_URL}/machines/${machine.id}/${action}`;
          const successMessage = `Machine ${
            action === "start" ? "started" : "stopped"
          } successfully.`;
          const errorMessage = `Failed to ${action} machine.`;

          try {
            runStopButton.disabled = true; // Disable button during operation
            runStopButton.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="1" fill="none" vector-effect="non-scaling-stroke"><line x1="12" y1="2" x2="12" y2="6"></line><line x1="12" y1="18" x2="12" y2="22"></line><line x1="4.93" y1="4.93" x2="7.76" y2="7.76"></line><line x1="16.24" y1="16.24" x2="19.07" y2="19.07"></line><line x1="2" y1="12" x2="6" y2="12"></line><line x1="18" y1="12" x2="22" y2="12"></line><line x1="4.93" y1="19.07" x2="7.76" y2="16.24"></line><line x1="16.24" y1="7.76" x2="19.07" y2="4.93"></line></svg>`; // Spinner icon

            const response = await fetch(endpoint, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify({}),
            });
            const result = await response.json();

            if (response.ok) {
              showMessage(result.message || successMessage, "success");
              fetchAndRenderMachines(); // Refresh list to show updated status
            } else {
              showMessage(`Error: ${result.detail || errorMessage}`, "error");
            }
          } catch (error) {
            console.error(`Error ${action}ing machine:`, error);
            showMessage(
              `An error occurred while ${action}ing the machine.`,
              "error"
            );
          } finally {
            runStopButton.disabled = false; // Re-enable button
            // The icon will be reset by fetchAndRenderMachines()
          }
        });
      } // End of if (!isButtonDisabled)

      // Settings and Delete buttons should always be clickable
      settingsButton.addEventListener("click", () => {
        openMachineDetailsSection(machine.id, machine.name);
      });

      deleteButton.addEventListener("click", () => {
        const confirmation = confirm(
          `Are you sure you want to delete machine "${machine.name}"? This action cannot be undone.`
        );
        if (confirmation) {
          deleteMachineItem(machine.id, machine.id, "machine");
        }
      });
    });
  };

  // Function to fetch and render activity logs
  const fetchAndRenderActivityLogs = async () => {
    const activityListDiv = document.querySelector(".activity-list");
    activityListDiv.innerHTML = "<p>Loading recent activity...</p>"; // Show loading message

    try {
      const response = await fetch(`${BASE_API_URL}/activity-logs`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const logsText = await response.text(); // Get raw text response

      activityListDiv.innerHTML = ""; // Clear loading message

      if (logsText.trim() === "No activity logs available yet.") {
        activityListDiv.innerHTML = "<p>No recent activity to display.</p>";
        return;
      }

      const logEntries = logsText.trim().split("\n").reverse().slice(0, 5); // Split by line, reverse, and cap to 5 most recent

      if (logEntries.length === 0) {
        activityListDiv.innerHTML = "<p>No recent activity to display.</p>";
        return;
      }

      // Add a class to make it scrollable if there are more than 5 entries (or a certain height)
      if (logsText.trim().split("\n").length > 5) {
        // Check original length before slicing
        activityListDiv.classList.add("scrollable-activity");
      } else {
        activityListDiv.classList.remove("scrollable-activity");
      }

      logEntries.forEach((entry) => {
        const activityItem = document.createElement("div");
        activityItem.classList.add("activity-item");

        // Parse timestamp and message
        const match = entry.match(
          /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\] (.+)$/
        );
        if (match) {
          const timestamp = match[1];
          const message = match[2];
          activityItem.innerHTML = `
            <p>${message}</p>
            <span>${timestamp}</span>
          `;
        } else {
          // Fallback for unparseable lines
          activityItem.innerHTML = `<p>${entry}</p>`;
        }
        activityListDiv.appendChild(activityItem);
      });
    } catch (error) {
      console.error("Error fetching activity logs:", error);
      activityListDiv.innerHTML = "<p>Failed to load recent activity.</p>";
    }
  };

  navLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();

      // Remove active class from current active link
      navLinks.forEach((nav) => nav.classList.remove("active"));
      // Add active class to clicked link
      link.classList.add("active");

      // Hide all content sections
      contentSections.forEach((section) => section.classList.remove("active"));

      // Show the corresponding content section
      const targetSectionId = link.dataset.section + "-section";
      const targetSection = document.getElementById(targetSectionId);
      if (targetSection) {
        targetSection.classList.add("active");
        if (link.dataset.section === "machine") {
          fetchAndRenderMachines(); // Initial fetch
        } else if (link.dataset.section === "overview") {
          fetchAndRenderActivityLogs();
          fetchAndRenderSshxUrl(); // Fetch SSHX URL when overview is active
        }
      }
    });
  });

  // New Machine Modal functionality
  newMachineModal.style.display = "none"; // Ensure new machine modal is hidden on initial load

  const toggleNewMachineModal = (show) => {
    if (show) {
      newMachineModal.style.display = "flex";
      document.body.classList.add("new-machine-modal-open");
      // Initialize the tag select box state
      dockerImageTagsSelect.innerHTML = ""; // Clear any previous tags
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = "Select Tag"; // Changed text
      dockerImageTagsSelect.appendChild(defaultOption);
      dockerImageTagsSelect.disabled = true; // Initially disabled
      updateCreateButtonState(); // Set initial button state
    } else {
      newMachineModal.style.display = "none";
      document.body.classList.remove("new-machine-modal-open");
      newMachineForm.reset(); // Clear form on close
      dockerImageInput.value = ""; // Clear docker image input
      dockerImageTagsSelect.innerHTML = ""; // Clear tags
      dockerImageTagsSelect.disabled = true; // Ensure it's disabled on close
      updateCreateButtonState(); // Reset button state
    }
  };

  newMachineBtn.addEventListener("click", () => {
    toggleNewMachineModal(true);
    // updateCreateButtonState() is called within toggleNewMachineModal now
  });

  closeModalBtn.addEventListener("click", () => {
    toggleNewMachineModal(false);
  });

  window.addEventListener("click", (event) => {
    if (event.target === newMachineModal) {
      toggleNewMachineModal(false);
    }
  });

  const openMachineDetailsSection = async (machineId, machineName) => {
    currentMachineId = machineId; // Store the current machine ID

    // Update the title
    machineDetailsTitle.textContent = `Details for ${machineName}`;

    // Hide all content sections
    contentSections.forEach((section) => section.classList.remove("active"));
    // Show the machine details section
    machineDetailsSection.classList.add("active");

    // Update active navigation link (optional, but good for consistency)
    navLinks.forEach((nav) => nav.classList.remove("active"));
    // Assuming you might want a "Machine Details" link in the future,
    // for now, we'll just ensure no main nav link is active or activate 'Machine'
    document
      .querySelector('.main-nav a[data-section="machine"]')
      .classList.add("active");

    // Reset tabs to default (Usage) and load content
    const tabButtons = machineDetailsSection.querySelectorAll(".tab-button");
    const tabContents = machineDetailsSection.querySelectorAll(".tab-content");

    tabButtons.forEach((btn) => btn.classList.remove("active"));
    tabContents.forEach((content) => content.classList.remove("active"));

    // Activate the first tab (Usage) by default
    tabButtons[0].classList.add("active");
    tabContents[0].classList.add("active");

    // Load initial tab content based on the default active tab
    const defaultTab = tabButtons[0].dataset.tab;
    if (defaultTab === "usage") {
      fetchMachineUsage(currentMachineId);
    } else if (defaultTab === "logs") {
      fetchMachineLogs(currentMachineId);
    } else if (defaultTab === "file-manager" && currentMachineId) {
      currentFilePath = "/"; // Reset path when opening file manager
      fetchMachineFiles(currentMachineId, currentFilePath);
    }
    // Destroy charts when opening machine details section, as a new machine might be selected
    destroyCharts();
  };

  // Docker Image Tag Fetching
  let dockerImageFetchTimeout;
  dockerImageInput.addEventListener("input", () => {
    clearTimeout(dockerImageFetchTimeout);
    const imageName = dockerImageInput.value.trim();
    if (imageName.length > 0) {
      // Fetch immediately if there's any input
      dockerImageTagsSelect.disabled = false; // Enable the select box
      dockerImageFetchTimeout = setTimeout(() => {
        fetchDockerImageTags(imageName);
      }, 300); // Reduced debounce time for quicker feedback
    } else {
      dockerImageTagsSelect.innerHTML = ""; // Clear tags
      const defaultOption = document.createElement("option");
      defaultOption.value = "";
      defaultOption.textContent = "Select Tag"; // Changed text
      dockerImageTagsSelect.appendChild(defaultOption);
      dockerImageTagsSelect.disabled = true; // Disable the select box
    }
    updateCreateButtonState();
  });

  dockerImageTagsSelect.addEventListener("change", () => {
    updateCreateButtonState();
  });

  const updateCreateButtonState = () => {
    const hasDockerImageInput = dockerImageInput.value.trim().length > 0;
    const isTagSelected = dockerImageTagsSelect.value.length > 0; // Checks if a non-empty option is selected

    // The button should be disabled if:
    // 1. The docker image input is empty, OR
    // 2. The docker image input has a value, but no specific tag is selected (i.e., the default empty option is selected)
    const shouldBeDisabled =
      !hasDockerImageInput || (hasDockerImageInput && !isTagSelected);

    createMachineBtn.disabled = shouldBeDisabled; // Keep the disabled attribute for accessibility/JS behavior
    if (shouldBeDisabled) {
      createMachineBtn.classList.add("is-disabled");
    } else {
      createMachineBtn.classList.remove("is-disabled");
    }
  };

  const fetchDockerImageTags = async (imageName) => {
    if (!imageName) {
      // Do not fetch if image name is empty
      populateDockerImageTags([]); // Clear and set default message
      return;
    }
    try {
      const response = await fetch(
        `${BASE_API_URL}/docker-images/search?query=${encodeURIComponent(
          imageName
        )}`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      populateDockerImageTags(data); // Pass the entire data array
    } catch (error) {
      console.error("Error fetching Docker image tags:", error);
      showMessage("Enter a valid Docker Image name", "error"); // Added this line
      //   dockerImageTagsSelect.innerHTML = '<option value="">Failed to load tags</option>';
      dockerImageTagsSelect.disabled = true; // Disable if fetching fails
      updateCreateButtonState();
    }
  };

  const populateDockerImageTags = (images) => {
    dockerImageTagsSelect.innerHTML = "";
    const defaultOption = document.createElement("option");
    defaultOption.value = "";
    defaultOption.textContent = "Select Tag"; // Changed text

    if (images && images.length > 0) {
      dockerImageTagsSelect.appendChild(defaultOption); // Add default option if tags are found
      images.forEach((image) => {
        const option = document.createElement("option");
        option.value = image.name;
        option.textContent = image.name;
        dockerImageTagsSelect.appendChild(option);
      });
      dockerImageTagsSelect.disabled = false; // Enable if tags are found
    } else {
      // If no images are found, update the default option's text and keep it disabled
      defaultOption.textContent = "No Tags Found"; // Changed text
      dockerImageTagsSelect.appendChild(defaultOption);
      dockerImageTagsSelect.disabled = true; // Keep disabled if no tags
    }
    updateCreateButtonState(); // Update button state after populating tags
  };

  // Tab switching logic for Machine Details Section
  machineDetailsSection.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => {
      // Clear any active usage interval when switching tabs
      if (currentUsageInterval) {
        clearInterval(currentUsageInterval);
        currentUsageInterval = null;
        console.log("Cleared usage polling interval.");
      }
      // Destroy charts when switching tabs
      destroyCharts();

      // Remove active class from all buttons and content within this section
      machineDetailsSection
        .querySelectorAll(".tab-button")
        .forEach((btn) => btn.classList.remove("active"));
      machineDetailsSection
        .querySelectorAll(".tab-content")
        .forEach((content) => content.classList.remove("active"));

      // Add active class to the clicked button and its corresponding content
      button.classList.add("active");
      const targetTabId = button.dataset.tab + "-tab";
      document.getElementById(targetTabId).classList.add("active");

      // If usage tab is clicked, fetch usage
      if (button.dataset.tab === "usage" && currentMachineId) {
        fetchMachineUsage(currentMachineId);
      } else if (button.dataset.tab === "logs" && currentMachineId) {
        fetchMachineLogs(currentMachineId);
      } else if (button.dataset.tab === "file-manager" && currentMachineId) {
        currentFilePath = "/"; // Reset path when opening file manager
        fetchMachineFiles(currentMachineId, currentFilePath);
      } else if (button.dataset.tab === "settings" && currentMachineId) {
        fetchMachineSettings(currentMachineId);
      }
    });
  });

  // Settings Functions
  const fetchMachineSettings = async (machineId) => {
    try {
      const response = await fetch(
        `${BASE_API_URL}/machines/${machineId}/settings`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const settings = await response.json();
      buildCommandInput.value = settings.build_command || "";
      installCommandInput.value = settings.install_command || "";
      runCommandInput.value = settings.run_command || "";
      forwardingPortInput.value = settings.forwarding_port || "";
      uniquePathInput.value = settings.unique_path || "";
      originalUniquePath = settings.unique_path || ""; // Store the original value

      // Update the unique path display link
      const uniquePathLink = document.getElementById("unique-path-link");
      const displayUniquePathSpan = document.getElementById(
        "display-unique-path"
      );
      if (uniquePathLink && displayUniquePathSpan) {
        const fullUrl = `https://goto-tau.vercel.app/${settings.unique_path}`;
        uniquePathLink.href = fullUrl;
        displayUniquePathSpan.textContent = settings.unique_path;
      }

      // Trigger validation after loading settings
      validateForwardingPort();
      // No need to call checkUniquePathAvailability here directly,
      // as the input event listener will handle it if the user types.
      // For initial load, if the path is the original, it's considered valid.
      isUniquePathAvailable = true; // Assume original path is valid
      uniquePathAvailabilityMessage.textContent = ""; // Clear any previous message
      updateSaveSettingsButtonState(); // Update button state based on initial validity
    } catch (error) {
      console.error("Error fetching machine settings:", error);
      showMessage("Failed to load machine settings.", "error");
    }
  };

  // Debounce function to limit API calls
  const debounce = (func, delay) => {
    let timeout;
    return function (...args) {
      const context = this;
      clearTimeout(timeout);
      timeout = setTimeout(() => func.apply(context, args), delay);
    };
  };

  // Validate Forwarding Port
  const validateForwardingPort = () => {
    const port = parseInt(forwardingPortInput.value);
    if (forwardingPortInput.value === "") {
      forwardingPortValidationMessage.textContent = "";
      isForwardingPortValid = true;
    } else if (isNaN(port) || port < 1 || port > 65535) {
      forwardingPortValidationMessage.textContent =
        "Port must be between 1 and 65535.";
      forwardingPortValidationMessage.classList.add("error");
      isForwardingPortValid = false;
    } else {
      forwardingPortValidationMessage.textContent = "";
      forwardingPortValidationMessage.classList.remove("error");
      isForwardingPortValid = true;
    }
    updateSaveSettingsButtonState();
  };

  // Check Unique Path Availability
  const checkUniquePathAvailability = debounce(async (path) => {
    const trimmedPath = path.trim();

    if (trimmedPath === "") {
      uniquePathAvailabilityMessage.textContent = "";
      isUniquePathAvailable = true;
      updateSaveSettingsButtonState();
      return;
    }

    // If the path is the same as the original loaded path, consider it available
    if (trimmedPath === originalUniquePath) {
      uniquePathAvailabilityMessage.textContent = "";
      isUniquePathAvailable = true;
      updateSaveSettingsButtonState();
      return;
    }

    uniquePathAvailabilityMessage.textContent = "Checking availability...";
    uniquePathAvailabilityMessage.classList.remove("error", "success");

    try {
      const response = await fetch(
        `${BASE_API_URL}/check-unique-path-availability/${path}`,
        {
          method: "GET",
        }
      );
      const result = await response.json(); // Parse JSON response from our backend

      if (result.available) {
        uniquePathAvailabilityMessage.textContent = "Available!";
        uniquePathAvailabilityMessage.classList.add("success");
        isUniquePathAvailable = true;
      } else {
        uniquePathAvailabilityMessage.textContent =
          "Not available. Please choose another.";
        uniquePathAvailabilityMessage.classList.add("error");
        isUniquePathAvailable = false;
      }
    } catch (error) {
      console.error("Error checking unique path availability:", error);
      uniquePathAvailabilityMessage.textContent =
        "Error checking availability.";
      uniquePathAvailabilityMessage.classList.add("error");
      isUniquePathAvailable = false;
    } finally {
      updateSaveSettingsButtonState();
    }
  }, 500); // Debounce by 500ms

  // Update Save Settings Button State
  const updateSaveSettingsButtonState = () => {
    const isFormValid = isForwardingPortValid && isUniquePathAvailable;
    saveSettingsBtn.disabled = !isFormValid;
    if (!isFormValid) {
      saveSettingsBtn.classList.add("is-disabled");
    } else {
      saveSettingsBtn.classList.remove("is-disabled");
    }
  };

  // Add event listeners for validation
  forwardingPortInput.addEventListener("input", validateForwardingPort);
  uniquePathInput.addEventListener("input", (e) =>
    checkUniquePathAvailability(e.target.value)
  );

  // Initial validation when the settings tab is opened
  // This is handled by fetchMachineSettings calling validateForwardingPort and checkUniquePathAvailability

  saveSettingsBtn.addEventListener("click", async () => {
    if (!currentMachineId) {
      showMessage("Please select a machine first.", "error");
      return;
    }

    const settingsData = {
      build_command: buildCommandInput.value,
      install_command: installCommandInput.value,
      run_command: runCommandInput.value,
      forwarding_port: forwardingPortInput.value,
      unique_path: uniquePathInput.value,
    };

    try {
      saveSettingsBtn.textContent = "Saving...";
      saveSettingsBtn.disabled = true;
      const response = await fetch(
        `${BASE_API_URL}/machines/${currentMachineId}/settings`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(settingsData),
        }
      );

      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to save settings"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error saving machine settings:", error);
      showMessage("An error occurred while saving settings.", "error");
    } finally {
      saveSettingsBtn.textContent = "Save Settings";
      saveSettingsBtn.disabled = false;
    }
  });

  // File Manager Functions
  const fetchMachineFiles = async (machineId, path) => {
    console.log(
      `Attempting to fetch files for machine ID: ${machineId}, path: ${path}`
    );
    fileListUl.innerHTML = "<li>Loading files...</li>";
    currentFilePathSpan.textContent = path;
    try {
      const response = await fetch(
        `${BASE_API_URL}/machines/${machineId}/files?path=${encodeURIComponent(
          path
        )}`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const files = await response.json(); // Expecting an array of {name: string, type: 'file' | 'folder'}

      fileListUl.innerHTML = ""; // Clear loading message

      // Add ".." for navigating up
      if (path !== "/") {
        const backLi = document.createElement("li");
        backLi.innerHTML = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"></polyline></svg> ..`;
        backLi.classList.add("folder");
        backLi.addEventListener("click", () => {
          const pathParts = path.split("/");
          pathParts.pop(); // Remove the last segment
          const parentPath = pathParts.join("/");
          fetchMachineFiles(machineId, parentPath === "" ? "/" : parentPath);
        });
        fileListUl.appendChild(backLi);
      }

      if (files.length === 0 && path === "/") {
        fileListUl.innerHTML +=
          "<li class='empty-folder'>No files or folders found.</li>";
      } else if (files.length === 0 && path !== "/") {
        fileListUl.innerHTML +=
          "<li class='empty-folder'>This folder is empty.</li>";
      }

      files.forEach((item) => {
        const li = document.createElement("li");
        li.classList.add(item.type);
        let icon = "";
        let actionsHtml = "";

        if (item.type === "folder") {
          icon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
          li.addEventListener("click", () => {
            const newPath =
              path === "/" ? `/${item.name}` : `${path}/${item.name}`;
            fetchMachineFiles(machineId, newPath);
          });
          // Add delete button for folders
          actionsHtml = `
            <button class="icon-button delete-folder-button" data-folder-name="${item.name}">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          `;
        } else {
          icon = `<svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>`;
          // Add delete button for files
          actionsHtml = `
            <button class="icon-button delete-file-button" data-file-name="${item.name}">
              <svg viewBox="0 0 24 24" width="16" height="16" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
            </button>
          `;
          // Add click listener to open file editor for files
          li.addEventListener("click", () => {
            const fullPath = path === "/" ? `/${item.name}` : `${path}/${item.name}`;
            openFileEditor(currentMachineId, fullPath);
          });
        }

        li.innerHTML = `
          <div class="file-info">
            ${icon} <span>${item.name}</span>
          </div>
          <div class="file-actions">
            ${actionsHtml}
          </div>
        `;
        fileListUl.appendChild(li);

        // Attach event listener for delete button if it exists
        if (item.type === "file") {
          const deleteButton = li.querySelector(".delete-file-button");
          if (deleteButton) {
            deleteButton.addEventListener("click", (e) => {
              e.stopPropagation(); // Prevent li click event from firing
              const fileName = deleteButton.dataset.fileName;
              const fullPath =
                path === "/" ? `/${fileName}` : `${path}/${fileName}`;
              const confirmation = confirm(
                `Are you sure you want to delete file "${fileName}"? This action cannot be undone.`
              );
              if (confirmation) {
                deleteMachineItem(currentMachineId, fullPath, "file");
              }
            });
          }
        } else if (item.type === "folder") {
          const deleteButton = li.querySelector(".delete-folder-button");
          if (deleteButton) {
            deleteButton.addEventListener("click", (e) => {
              e.stopPropagation(); // Prevent li click event from firing
              const folderName = deleteButton.dataset.folderName;
              const fullPath =
                path === "/" ? `/${folderName}` : `${path}/${folderName}`;
              const confirmation = confirm(
                `Are you sure you want to delete folder "${folderName}"? This action cannot be undone.`
              );
              if (confirmation) {
                deleteMachineItem(currentMachineId, fullPath, "folder");
              }
            });
          }
        }
      });
    } catch (error) {
      console.error("Error fetching machine files:", error);
      fileListUl.innerHTML = `<li class='error-item'>Failed to load files for machine ${machineId}. Please ensure the backend is running and supports file browsing.</li>`;
    }
  };

  // Function to delete a file or folder (unified)
  const deleteMachineItem = async (machineId, itemPath, itemType) => {
    try {
      showMessage(`Deleting ${itemType} ${itemPath}...`, "info");
      let endpoint;
      if (itemType === "machine") {
        endpoint = `${BASE_API_URL}/machines/delete/${machineId}`;
      } else {
        endpoint = `${BASE_API_URL}/machines/${machineId}/${itemType}s?path=${encodeURIComponent(
          itemPath
        )}`; // Dynamically choose endpoint for files/folders
      }
      const response = await fetch(endpoint, {
        method: "DELETE",
      });
      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
        if (itemType === "machine") {
          fetchAndRenderMachines(); // Refresh machine list if a machine was deleted
        } else {
          fetchMachineFiles(machineId, currentFilePath); // Refresh file list if a file/folder was deleted
        }
      } else {
        showMessage(
          `Error: ${result.detail || `Failed to delete ${itemType}`}`,
          "error"
        );
      }
    } catch (error) {
      console.error(`Error deleting ${itemType}:`, error);
      showMessage(`An error occurred during ${itemType} deletion.`, "error");
    }
  };

  // Unified File Upload Function
  const uploadFiles = async (files) => {
    if (!currentMachineId) {
      showMessage("Please select a machine first.", "error");
      return;
    }
    if (files.length === 0) {
      showMessage("No files selected for upload.", "error");
      return;
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append("files", file);
    }

    try {
      // Indicate uploading state on the drop zone or a global message
      showMessage(`Uploading ${files.length} file(s)...`, "info");
      dropZone.classList.add("uploading"); // Add a class for visual feedback

      const response = await fetch(
        `${BASE_API_URL}/machines/${currentMachineId}/upload?path=${encodeURIComponent(
          currentFilePath
        )}`,
        {
          method: "POST",
          body: formData,
        }
      );
      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
        fetchMachineFiles(currentMachineId, currentFilePath); // Refresh file list
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to upload files"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error uploading files:", error);
      showMessage("An error occurred during file upload.", "error");
    } finally {
      dropZone.classList.remove("uploading"); // Remove uploading state
    }
  };

  // Drag and Drop functionality
  // Prevent default drag behaviors
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => e.preventDefault());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      uploadFiles(files);
    }
  });

  // "Browse Files" button functionality
  browseFilesBtn.addEventListener("click", () => {
    fileUploadInput.click(); // Trigger the hidden file input click
  });

  fileUploadInput.addEventListener("change", (e) => {
    const files = e.target.files;
    if (files.length > 0) {
      uploadFiles(files);
    }
    fileUploadInput.value = ""; // Clear the input after selection
  });

  // Git Clone
  gitCloneBtn.addEventListener("click", async () => {
    if (!currentMachineId) {
      showMessage("Please select a machine first.", "error");
      return;
    }
    const repoUrl = gitRepoUrlInput.value.trim();
    if (!repoUrl) {
      showMessage("Please enter a Git repository URL.", "error");
      return;
    }

    try {
      gitCloneBtn.textContent = "Cloning...";
      gitCloneBtn.disabled = true;
      const response = await fetch(
        `${BASE_API_URL}/machines/${currentMachineId}/git-clone?path=${encodeURIComponent(
          currentFilePath
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ repo_url: repoUrl }),
        }
      );
      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
        gitRepoUrlInput.value = ""; // Clear input
        fetchMachineFiles(currentMachineId, currentFilePath); // Refresh file list
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to clone repository"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error cloning repository:", error);
      showMessage("An error occurred during Git clone.", "error");
    } finally {
      gitCloneBtn.textContent = "Git Clone";
      gitCloneBtn.disabled = false;
    }
  });

  const usageCpuSpan = document.getElementById("usage-cpu");
  const usageRamSpan = document.getElementById("usage-ram");
  const usageNetIoSpan = document.getElementById("usage-net-io");
  const usageTabContent = document.getElementById("usage-tab"); // Reference to the usage tab content

  const cpuUsageChartCtx = document.getElementById("cpuUsageChart").getContext("2d");
  const ramUsageChartCtx = document.getElementById("ramUsageChart").getContext("2d");
  const netIoChartCtx = document.getElementById("netIoChart").getContext("2d");

  const updateUsageDisplay = (data) => {
    usageCpuSpan.textContent = data.cpu_percent || "N/A";
    usageRamSpan.textContent = `${data.mem_usage || "N/A"} / ${
      data.mem_limit || "N/A"
    }`;
    usageNetIoSpan.textContent = `${data.net_rx || "N/A"} / ${
      data.net_tx || "N/A"
    }`;
  };

  const renderCharts = (history) => {
    const labels = history.map((item) =>
      new Date(item.timestamp).toLocaleTimeString()
    );
    const cpuData = history.map((item) =>
      parseFloat(item.cpu_percent.replace("%", ""))
    );
    const ramUsageData = history.map((item) =>
      parseFloat(item.mem_usage.replace(/[^0-9.]/g, ""))
    );
    const ramLimitData = history.map((item) =>
      parseFloat(item.mem_limit.replace(/[^0-9.]/g, ""))
    );
    const netRxData = history.map((item) =>
      parseFloat(item.net_rx.replace(/[^0-9.]/g, ""))
    );
    const netTxData = history.map((item) =>
      parseFloat(item.net_tx.replace(/[^0-9.]/g, ""))
    );

    // CPU Chart
    if (cpuChart) cpuChart.destroy();
    cpuChart = new Chart(cpuUsageChartCtx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "CPU Usage (%)",
            data: cpuData,
            borderColor: "rgb(75, 192, 192)",
            tension: 0.1,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: "CPU (%)",
            },
          },
          x: {
            title: {
              display: true,
              text: "Time",
            },
          },
        },
      },
    });

    // RAM Chart
    if (ramChart) ramChart.destroy();
    ramChart = new Chart(ramUsageChartCtx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "RAM Usage (MB)",
            data: ramUsageData,
            borderColor: "rgb(255, 99, 132)",
            tension: 0.1,
            fill: false,
          },
          {
            label: "RAM Limit (MB)",
            data: ramLimitData,
            borderColor: "rgb(54, 162, 235)",
            tension: 0.1,
            fill: false,
            borderDash: [5, 5],
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: "RAM (MB)",
            },
          },
          x: {
            title: {
              display: true,
              text: "Time",
            },
          },
        },
      },
    });

    // Network I/O Chart
    if (netIoChart) netIoChart.destroy();
    netIoChart = new Chart(netIoChartCtx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Net RX (MB)",
            data: netRxData,
            borderColor: "rgb(255, 205, 86)",
            tension: 0.1,
            fill: false,
          },
          {
            label: "Net TX (MB)",
            data: netTxData,
            borderColor: "rgb(153, 102, 255)",
            tension: 0.1,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          y: {
            beginAtZero: true,
            title: {
              display: true,
              text: "Network I/O (MB)",
            },
          },
          x: {
            title: {
              display: true,
              text: "Time",
            },
          },
        },
      },
    });
  };

  const pollMachineUsage = async (machineId) => {
    try {
      const [snapshotResponse, historyResponse] = await Promise.all([
        fetch(`${BASE_API_URL}/machines/${machineId}/usage-snapshot`),
        fetch(`${BASE_API_URL}/machines/${machineId}/usage-history`),
      ]);

      if (!snapshotResponse.ok) {
        throw new Error(`HTTP error! status: ${snapshotResponse.status}`);
      }
      if (!historyResponse.ok) {
        throw new Error(`HTTP error! status: ${historyResponse.status}`);
      }

      const snapshotData = await snapshotResponse.json();
      const historyData = await historyResponse.json();

      if (snapshotData.error) {
        console.error("Error from usage snapshot:", snapshotData.error);
        updateUsageDisplay({ cpu_percent: "Error", mem_usage: "Error", mem_limit: "", net_rx: "Error", net_tx: "" });
        showMessage(`Usage data error: ${snapshotData.error}`, "error");
        if (currentUsageInterval) {
          clearInterval(currentUsageInterval);
          currentUsageInterval = null;
        }
        destroyCharts(); // Destroy charts on error
        return;
      }
      updateUsageDisplay(snapshotData);
      renderCharts(historyData); // Render charts with historical data

    } catch (error) {
      console.error("Error fetching usage data:", error);
      updateUsageDisplay({ cpu_percent: "Error", mem_usage: "Error", mem_limit: "", net_rx: "Error", net_tx: "" });
      showMessage("Failed to fetch usage data.", "error");
      if (currentUsageInterval) {
        clearInterval(currentUsageInterval);
        currentUsageInterval = null;
      }
      destroyCharts(); // Destroy charts on error
    }
  };

  const fetchMachineUsage = (machineId) => {
    // Clear any existing interval before setting a new one
    if (currentUsageInterval) {
      clearInterval(currentUsageInterval);
      currentUsageInterval = null;
    }
    // Destroy existing charts before fetching new data
    destroyCharts();

    usageCpuSpan.textContent = "Loading...";
    usageRamSpan.textContent = "Loading...";
    usageNetIoSpan.textContent = "Loading...";

    // Fetch immediately, then set interval
    pollMachineUsage(machineId);
    currentUsageInterval = setInterval(() => pollMachineUsage(machineId), 3000); // Poll every 3 seconds
    console.log("Started usage polling interval.");
  };

  const fetchMachineLogs = async (machineId) => {
    machineLogsPre.textContent = "Connecting to logs stream...";
    try {
      const response = await fetch(`/machines/${machineId}/logs`);
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulatedLogs = "";
      // Initialize AnsiUp, checking for common global exposures
      const AnsiUpConstructor = window.AnsiUp || (window.AnsiUp && window.AnsiUp.default);
      if (!AnsiUpConstructor) {
        console.error("AnsiUp library not found. Please ensure ansi_up.js is loaded correctly.");
        machineLogsPre.textContent = `Failed to load logs: AnsiUp library is missing.`;
        return; // Exit the function if AnsiUp is not available
      }
      const ansi_up = new AnsiUpConstructor();

      machineLogsPre.innerHTML = ""; // Clear initial message once stream starts

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          console.log("Logs stream finished.");
          break;
        }
        const chunk = decoder.decode(value, { stream: true });
        console.log("Raw log chunk:", chunk); // Debug raw log content
        accumulatedLogs += chunk;
        const processedHtml = ansi_up.ansi_to_html(accumulatedLogs);
        console.log("Processed HTML:", processedHtml); // Debug processed HTML
        machineLogsPre.innerHTML = processedHtml; // Convert ANSI to HTML and update content
        machineLogsPre.scrollTop = machineLogsPre.scrollHeight; // Auto-scroll to bottom
      }
    } catch (error) {
      console.error("Error fetching machine logs:", error);
      machineLogsPre.textContent = `Failed to load logs for machine ${machineId}. Please ensure the backend is running and supports log fetching. Error: ${error.message}`;
    }
  };

  // Handle form submission
  newMachineForm.addEventListener("submit", async (e) => {
    e.preventDefault();

    const name = document.getElementById("machine-name").value;
    const ram = parseInt(document.getElementById("machine-ram").value);
    const core = parseInt(document.getElementById("machine-core").value);
    const dockerImage = `${dockerImageInput.value}:${dockerImageTagsSelect.value}`;

    const newMachineData = {
      name,
      ram,
      core,
      docker_image: dockerImage,
    };

    try {
      const response = await fetch("/machines/create", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(newMachineData),
      });

      const result = await response.json();

      if (response.ok) {
        showMessage(result.message, "success");
        toggleNewMachineModal(false); // Close modal and reset form
        fetchAndRenderMachines(); // Refresh machine list
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to create machine"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error creating machine:", error);
      showMessage("An error occurred while creating the machine.", "error");
    }
  });

  // Initial call to set button state for new machine modal
  updateCreateButtonState();

  const fetchAndRenderSshxUrl = async () => {
    const sshxLink = document.getElementById("sshx-link");
    if (!sshxLink) return; // Ensure the element exists

    sshxLink.textContent = "Loading...";
    sshxLink.href = "#"; // Reset href

    try {
      const response = await fetch(`${BASE_API_URL}/sshx-url`);
      if (response.ok) {
        const data = await response.json();
        const url = data.sshx_url;
        sshxLink.textContent = url;
        sshxLink.href = url;
      } else if (response.status === 404) {
        sshxLink.textContent = "Not available (run sshx.py)";
        sshxLink.href = "#";
      } else {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
    } catch (error) {
      console.error("Error fetching SSHX URL:", error);
      sshxLink.textContent = "Failed to load SSHX URL";
      sshxLink.href = "#";
      showMessage("Failed to load SSHX URL.", "error");
    }
  };

  // Initial load: if the URL hash indicates a section, activate it. Otherwise, default to overview.
  const initialSection = window.location.hash.substring(1) || "overview";
  const initialNavLink = document.querySelector(
    `.main-nav a[data-section="${initialSection}"]`
  );
  if (initialNavLink) {
    initialNavLink.click(); // Simulate a click to activate the section and load data
  } else {
    // Fallback to overview if hash is invalid
    document.querySelector('.main-nav a[data-section="overview"]').click();
  }

  // Ensure initial state of save settings button is correct when page loads
  updateCreateButtonState();

  // File Editor Functions
  const openFileEditor = async (machineId, filePath) => {
    if (!machineId || !filePath) {
      showMessage("Machine ID or file path is missing.", "error");
      return;
    }

    currentEditingFilePath = filePath; // Store the path of the file being edited
    editingFilePathSpan.textContent = filePath;
    fileEditorTextarea.value = "Loading file content...";
    fileEditorModal.style.display = "flex";
    document.body.classList.add("new-machine-modal-open"); // Reuse modal-open class for blur effect

    try {
      const response = await fetch(
        `${BASE_API_URL}/machines/${machineId}/files/content?path=${encodeURIComponent(
          filePath
        )}`
      );
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const content = await response.text();
      fileEditorTextarea.value = content;
    } catch (error) {
      console.error("Error fetching file content:", error);
      fileEditorTextarea.value = `Failed to load file content: ${error.message}`;
      showMessage("Failed to load file content.", "error");
    }
  };

  const saveFileContent = async () => {
    if (!currentMachineId || !currentEditingFilePath) {
      showMessage("No file selected for saving.", "error");
      return;
    }

    const content = fileEditorTextarea.value;

    try {
      saveFileContentBtn.textContent = "Saving...";
      saveFileContentBtn.disabled = true;

      const response = await fetch(
        `${BASE_API_URL}/machines/${currentMachineId}/files/content?path=${encodeURIComponent(
          currentEditingFilePath
        )}`,
        {
          method: "PUT",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ content: content }),
        }
      );

      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
        closeFileEditor();
        fetchMachineFiles(currentMachineId, currentFilePath); // Refresh file list after saving
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to save file content"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error saving file content:", error);
      showMessage("An error occurred while saving file content.", "error");
    } finally {
      saveFileContentBtn.textContent = "Save";
      saveFileContentBtn.disabled = false;
    }
  };

  const closeFileEditor = () => {
    fileEditorModal.style.display = "none";
    document.body.classList.remove("new-machine-modal-open");
    fileEditorTextarea.value = ""; // Clear content
    editingFilePathSpan.textContent = ""; // Clear path
    currentEditingFilePath = null; // Clear stored path
  };

  // Event Listeners for File Editor Modal
  closeFileEditorModalBtn.addEventListener("click", closeFileEditor);
  saveFileContentBtn.addEventListener("click", saveFileContent);

  window.addEventListener("click", (event) => {
    if (event.target === fileEditorModal) {
      closeFileEditor();
    }
  });

  // Create File Modal elements
  const newFileBtn = document.getElementById("new-file-btn");
  const createFileModal = document.getElementById("create-file-modal");
  const closeCreateFileModalBtn = document.getElementById("close-create-file-modal");
  const createFilePathSpan = document.getElementById("create-file-path-span");
  const newFileNameInput = document.getElementById("new-file-name");
  const newFileContentTextarea = document.getElementById("new-file-content");
  const createNewFileBtn = document.getElementById("create-new-file-btn");
  const createFileForm = document.getElementById("create-file-form");


  // Create File Functions
  const openCreateFileModal = () => {
    if (!currentMachineId) {
      showMessage("Please select a machine first.", "error");
      return;
    }
    createFilePathSpan.textContent = currentFilePath;
    createFileModal.style.display = "flex";
    document.body.classList.add("new-machine-modal-open"); // Reuse modal-open class for blur effect
  };

  const createNewFile = async (e) => {
    e.preventDefault(); // Prevent default form submission

    if (!currentMachineId) {
      showMessage("No machine selected for file creation.", "error");
      return;
    }

    const fileName = newFileNameInput.value.trim();
    const fileContent = newFileContentTextarea.value;

    if (!fileName) {
      showMessage("File name cannot be empty.", "error");
      return;
    }

    try {
      createNewFileBtn.textContent = "Creating...";
      createNewFileBtn.disabled = true;

      const response = await fetch(
        `${BASE_API_URL}/machines/${currentMachineId}/files?path=${encodeURIComponent(
          currentFilePath
        )}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ file_name: fileName, content: fileContent }),
        }
      );

      const result = await response.json();
      if (response.ok) {
        showMessage(result.message, "success");
        closeCreateFileModal();
        fetchMachineFiles(currentMachineId, currentFilePath); // Refresh file list after creating
      } else {
        showMessage(
          `Error: ${result.detail || "Failed to create file"}`,
          "error"
        );
      }
    } catch (error) {
      console.error("Error creating file:", error);
      showMessage("An error occurred while creating the file.", "error");
    } finally {
      createNewFileBtn.textContent = "Create File";
      createNewFileBtn.disabled = false;
    }
  };

  const closeCreateFileModal = () => {
    createFileModal.style.display = "none";
    document.body.classList.remove("new-machine-modal-open");
    newFileNameInput.value = ""; // Clear file name
    newFileContentTextarea.value = ""; // Clear content
    createFilePathSpan.textContent = ""; // Clear path
  };

  // Event Listeners for Create File Modal
  newFileBtn.addEventListener("click", openCreateFileModal);
  closeCreateFileModalBtn.addEventListener("click", closeCreateFileModal);
  createFileForm.addEventListener("submit", createNewFile);

  window.addEventListener("click", (event) => {
    if (event.target === createFileModal) {
      closeCreateFileModal();
    }
  });

  // Logout functionality
  const logoutLink = document.getElementById("logout-link");
  if (logoutLink) {
    logoutLink.addEventListener("click", async (e) => {
      e.preventDefault();
      try {
        const response = await fetch("/logout", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
        });

        if (response.ok) {
          showMessage("Logged out successfully.", "success");
          window.location.reload(); // Force a full page reload after logout
        } else {
          const errorData = await response.json();
          showMessage(errorData.detail || "Logout failed.", "error");
        }
      } catch (error) {
        console.error("Error during logout:", error);
        showMessage("An unexpected error occurred during logout.", "error");
      }
    });
  }
});
