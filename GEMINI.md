# LLM Benchmark - Project Documentation

## 1. Project Overview
This project is a comprehensive system for benchmarking, evaluating, and visualizing the performance of Large Language Models (LLMs). It automates the process of sending prompts to various models (hosted via Ollama), recording their responses and performance metrics, evaluating the quality of those responses using a superior model (Google Gemini), and presenting the data in a web-based dashboard.

## 2. Architecture
The system follows a modular architecture integrating Python automation, a MySQL database, and a PHP web interface.

*   **Execution Engine (Python):** Scripts to interact with the Ollama API, manage the benchmark workflow, and perform automated evaluations.
*   **Storage (MySQL):** A central relational database storing:
    *   Prompts (`prompts`)
    *   Model Metadata (`model_metadata`)
    *   Raw Benchmark Results (`benchmark_results`)
    *   Quality Evaluations (`evaluation_results`)
*   **Frontend (PHP):** A dynamic web dashboard for:
    *   Viewing side-by-side comparisons of model outputs.
    *   Analyzing performance graphs (latency, tokens/sec).
    *   Reviewing quality scores assigned by the evaluator.
*   **Inference Server:** Relying on [Ollama](https://ollama.ai/) to host and run the local LLMs.

## 3. Key Components

### 3.1 Python Scripts
*   **`benchmark.py`**: The core runner.
    *   Connects to the MySQL DB to fetch prompts.
    *   Iterates through specified models via the Ollama API.
    *   Records response text, duration, token counts, and errors into `benchmark_results`.
*   **`model_metadata.py`**: Fetches technical details (parameters, quantization, family) from Ollama and updates the `model_metadata` table.
*   **`gemini_evaluate.py`**: An automated grader.
    *   Reads unevaluated responses from `benchmark_results`.
    *   Uses either Google Gemini API or an OpenAI-compatible API (e.g., GPT-4, Ollama, vLLM) to score responses.
    *   Configurable via `.env` (EVALUATOR_TYPE, EVAL_BASE_URL, EVAL_MODEL, EVAL_API_KEY).
    *   Saves detailed justifications and scores to `evaluation_results`.
*   **`results.py`**: (Presumably) A utility for analyzing or aggregating results from the CLI.

### 3.2 Web Interface (PHP)
*   **`index.php`**: The main view. Displays a matrix of prompts vs. models, showing the actual text response and timing data.
*   **`graphs.php`**: Visualization page using charts to compare quantitative metrics.
*   **`ajax.php`**: Provides JSON data endpoints for the frontend components.
*   **`config.php`**: Database connection settings (ignored by git, template in `config-dist.php`).

### 3.3 Database Schema (`schema.sql`)
*   **`prompts`**: Holds the test questions/instructions.
*   **`benchmark_results`**: Links `prompts` to `model` executions. Stores `total_duration`, `eval_count` (output tokens), `prompt_eval_count` (input tokens), etc.
*   **`evaluation_results`**: Links to `benchmark_results`. Contains scores (1-10) and text justifications.
*   **`model_metadata`**: Stores static attributes of the models.

## 4. Setup & Configuration

### Prerequisites
*   **Python 3.x**: With `mysql-connector-python`, `requests`, `google-genai`, `python-dotenv`.
*   **PHP 7.4+**: With `pdo_mysql` extension.
*   **MySQL/MariaDB**: Server instance.
*   **Ollama**: Running locally or on a network accessible server.

### Installation
1.  **Database:**
    *   Run `schema.sql` to create the database and tables.
    *   Create a user (e.g., `llmuser`) with full privileges on the database.
2.  **Configuration (Python):**
    *   Create a `.env` file for API keys and evaluator settings.
    *   Fields: `GEMINI_API_KEY`, `EVALUATOR_TYPE` (gemini/openai), `EVAL_BASE_URL`, `EVAL_MODEL`, `EVAL_API_KEY`.
3.  **Configuration (PHP):**
    *   Copy `config-dist.php` to `config.php`.
    *   Update database credentials in `config.php`.

## 5. Usage

### Running Benchmarks
Use the provided `.bat` files or run directly:
```bash
python benchmark.py --host <DB_HOST> --user <DB_USER> --password <DB_PASS> --database <DB_NAME> --ollama <OLLAMA_URL>
```

### Fetching Metadata
```bash
python model_metadata.py --host <DB_HOST> ...
```

### Running Evaluations
```bash
python gemini_evaluate.py --host <DB_HOST> ...
```

### Viewing Results
Serve the PHP files via a web server (e.g., Apache, Nginx, or `php -S localhost:8000`) and navigate to `index.php`.

## 6. Development Notes
*   **Extending Prompts:** Add new entries to the `prompts` table via SQL or a future admin interface.
*   **Adding Models:** Pull the model in Ollama (`ollama pull modelname`). The benchmark script iterates over available models or can be restricted.
*   **Security:** Ensure `config.php` and `.env` are never committed (enforced by `.gitignore`).
