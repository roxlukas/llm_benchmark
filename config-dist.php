<?php
// Configuration file for LLM Benchmark application
// This file contains sensitive credentials and should be secured appropriately

// Database connection settings
$dbConfig = [
    'host' => 'localhost',
    'port' => 3306,
    'user' => 'llmuser',
    'password' => 'password',
    'database' => 'llm_benchmark'
];

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