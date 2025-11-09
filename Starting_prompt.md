Your task is to design and build an advanced, automated media-organizing application.

The application consists of a multi-threaded Python backend for file monitoring and processing, and a local Flask web interface for monitoring, manual intervention, and full application configuration.

The system must intelligently pre-process files from a "downloading" folder and execute organization when they arrive in a "completed" folder, with all states and actions visible and controllable via the web UI.

## 1. Core Architecture & Configuration

    Backend: A multi-threaded Python application managing file watchers, processing queues, and the "Job Store."

    Frontend (Web Interface): A Flask server running locally on port 7000.

    Configuration (Dynamic): A central config.json file (or similar) will store all non-secret settings (paths, model names, timers). The Flask web UI will read from and write to this file. The backend threads must detect changes to this file and reload their configuration live.

    Configuration (Secure): A separate .env file, readable only by the backend. This file will store all API keys (OpenAI, Google, etc.). The web interface must never read, display, or write these keys.

    Central Job Store: A thread-safe "Job List" (e.g., a simple database or a stateful Python object) that tracks the state of every file detected (job_id, original_relative_path, status, ai_determined_name, etc.).

## 2. Backend Logic: Automated Workflow

The automated system runs continuously, pulling its parameters from the current configuration.

    Stage 1: Monitor, Debounce, & Batch-Process (from Downloading Path)

        A thread watches the DOWNLOADING_PATH for new files, adding them to a "Pending AI Queue" with a status of QUEUED_FOR_AI.

        A debounce timer (configurable DEBOUNCE_SECONDS) starts/resets.

        When the timer completes, a processor thread:

            Gathers all QUEUED_FOR_AI jobs.

            Chunks them (configurable AI_BATCH_SIZE).

            For each chunk, it reads the current AI_PROVIDER and AI_MODEL from the configuration.

            It sends the batch to the selected AI, setting job statuses to PROCESSING_AI.

            On success, it updates each job with the AI's response and sets the status to PENDING_COMPLETION.

    Stage 2: Execute & Organize (in Completed Path)

        A separate thread watches the COMPLETED_PATH.

        When a file appears, it finds the matching PENDING_COMPLETION job in the Job Store.

        It uses the job's data to rename and move the file to the LIBRARY_PATH.

        It sets the job status to COMPLETED.

## 3. Web Interface & Priority Queue (Flask on Port 7000)

The Flask server provides the full user-facing experience.

Main View (/)

    An auto-refreshing dashboard showing all active jobs from the Central Job Store.

    Displays: Original Path, Status ("Queued for AI", "Processing", "Pending Move"), and New Name.

Job Control

    Manual Edit: Allows a user to directly set the new_name and new_path for a job, setting its status to PENDING_COMPLETION and removing it from all AI queues.

    Intelligent Rename (Re-AI):

        A "Re-AI" button for each job, opening a form (custom prompt, "include default instructions" checkbox, etc.).

        Submitting this form adds the job to a Priority AI Queue.

        A dedicated backend thread immediately processes jobs from this priority queue (one-by-one), bypassing the batching system.

Settings Page (/settings)

This new page allows full, runtime configuration of the application.

    Configuration Management:

        The page loads its values from the backend's current config.json.

        A "Save" button writes the new values back to the config.json file, which the backend threads will then reload.

    Configurable Fields (Settable in UI):

        DOWNLOADING_PATH (text input)

        COMPLETED_PATH (text input)

        LIBRARY_PATH (text input)

        DEBOUNCE_SECONDS (number input)

        AI_BATCH_SIZE (number input)

        INSTRUCTIONS_FILE_PATH (text input, path to the prompt file)

    Dynamic AI Settings (Settable in UI):

        AI Provider: A dropdown menu to select AI_PROVIDER (e.g., "openai", "google", "ollama").

        Available Models: A second dropdown menu for AI_MODEL.

        Dynamic Loading: When the user changes the "AI Provider" (e.g., selects "ollama"), the Flask app will:

            Make a call to its own backend (e.g., POST /api/get_models).

            The backend, using the API key from the .env file, will query the provider's API (e.g., http://localhost:11434/api/tags for Ollama, or OpenAI's /v1/models endpoint).

            The backend returns the list of model names to the frontend.

            The "Available Models" dropdown is then populated with this dynamic list, allowing the user to select one.

## 4. Full Configuration List

config.json (Managed by Web UI)

    DOWNLOADING_PATH

    COMPLETED_PATH

    LIBRARY_PATH

    INSTRUCTIONS_FILE_PATH

    DEBOUNCE_SECONDS

    AI_BATCH_SIZE

    AI_PROVIDER: (e.g., "ollama")

    AI_MODEL: (e.g., "llama3:latest")

    OLLAMA_API_URL: (Default: http://localhost:11434)

    DRY_RUN_MODE: (true/false)

    ENABLE_WEB_SEARCH: (true/false)

.env (Manual file, NOT in UI)

    OPENAI_API_KEY

    GOOGLE_API_KEY

    (Any other secret keys)