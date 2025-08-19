-- Create the database if it doesn't exist
CREATE DATABASE IF NOT EXISTS llm_benchmark;

USE llm_benchmark;

-- Table to store prompts
CREATE TABLE IF NOT EXISTS prompts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prompt_text TEXT NOT NULL,
    category VARCHAR(100),
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table to store benchmark results
CREATE TABLE IF NOT EXISTS benchmark_results (
    id INT AUTO_INCREMENT PRIMARY KEY,
    prompt_id INT NOT NULL,
    model VARCHAR(100) NOT NULL,
    success BOOLEAN NOT NULL,
    response_text TEXT,
    error TEXT,
    total_duration FLOAT,
    eval_count INT,
    eval_duration FLOAT,
    load_duration FLOAT,
    prompt_eval_count INT,
    prompt_eval_duration FLOAT,
    timestamp DATETIME,
    FOREIGN KEY (prompt_id) REFERENCES prompts(id),
    INDEX (model),
    INDEX (prompt_id)
);

-- Sample data for the prompts table
INSERT INTO prompts (prompt_text, category, tags) VALUES
('Explain quantum computing in simple terms', 'Education', 'science,physics,quantum'),
('Write a short story about a robot discovering emotions', 'Creative', 'fiction,robot,emotions'),
('What are the key differences between Python and JavaScript?', 'Programming', 'python,javascript,comparison'),
('Create a meal plan for a vegetarian athlete', 'Health', 'diet,nutrition,vegetarian,athlete'),
('Explain the implications of artificial general intelligence', 'AI', 'agi,future,ethics');

-- Table to store model metadata
CREATE TABLE IF NOT EXISTS model_metadata (
    model_name VARCHAR(100) PRIMARY KEY,
    architecture VARCHAR(50),
    parameters VARCHAR(20),
    context_length INT,
    embedding_length INT,
    quantization VARCHAR(20),
    stop_tokens TEXT,
    license_text TEXT,
    release_date DATE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX (model_name)
);