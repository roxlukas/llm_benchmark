<?php
// Configuration file for LLM Benchmark application
// Credentials live in .env next to this file (see .env.example); this file holds no secrets

// Read KEY=value lines from .env; # comments and surrounding quotes are allowed
function loadEnv($path) {
    $env = [];
    if (!is_readable($path)) {
        return $env;
    }
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#' || strpos($line, '=') === false) {
            continue;
        }
        [$key, $value] = array_map('trim', explode('=', $line, 2));
        if (strlen($value) >= 2 && ($value[0] === '"' || $value[0] === "'") && substr($value, -1) === $value[0]) {
            $value = substr($value, 1, -1);
        }
        $env[$key] = $value;
    }
    return $env;
}

$env = loadEnv(__DIR__ . '/.env');

// Database connection settings
$dbConfig = [
    'host' => $env['DB_HOST'] ?? 'localhost',
    'port' => (int)($env['DB_PORT'] ?? 3306),
    'user' => $env['DB_USER'] ?? '',
    'password' => $env['DB_PASSWORD'] ?? '',
    'database' => $env['DB_NAME'] ?? 'llm_benchmark'
];

// Evaluator whose scores (evaluation_results.evaluator) are shown in the UI
define('ACTIVE_EVALUATOR', $env['ACTIVE_EVALUATOR'] ?? 'anthropic/claude-haiku-5-5');

// Function to get database connection
function getDatabaseConnection() {
    global $dbConfig;

    try {
        $dsn = "mysql:host={$dbConfig['host']};port={$dbConfig['port']};dbname={$dbConfig['database']}";
        $pdo = new PDO($dsn, $dbConfig['user'], $dbConfig['password'], [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
        ]);
        return $pdo;
    } catch (PDOException $e) {
        die("Database connection failed: " . $e->getMessage());
    }
}
?>
