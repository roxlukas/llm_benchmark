<?php
/**
 * LLM Benchmark Results Comparison Table Generator (Simple Version)
 * 
 * This script generates an HTML table comparing responses from different LLM models
 * with the original prompts and timing information.
 */

// Database connection settings ($dbConfig) live in config.php, which is not committed
require_once 'config.php';

// Get models to include from GET parameters, or use all models if not specified
$selectedModels = isset($_GET['models']) ? explode(',', $_GET['models']) : [];

// Connect to the database
try {
    $dsn = "mysql:host={$dbConfig['host']};port={$dbConfig['port']};dbname={$dbConfig['database']}";
    $pdo = new PDO($dsn, $dbConfig['user'], $dbConfig['password'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
    ]);
    
    // Get all available models if none specified
    if (empty($selectedModels)) {
        $stmt = $pdo->query("SELECT DISTINCT model FROM benchmark_results ORDER BY model");
        $selectedModels = $stmt->fetchAll(PDO::FETCH_COLUMN);
    }
    
    // Get all prompts
    $stmt = $pdo->query("SELECT id, prompt_text, category, tags FROM prompts ORDER BY category, id");
    $prompts = $stmt->fetchAll();
    
    // Get all results for the selected models
    $placeholders = implode(',', array_fill(0, count($selectedModels), '?'));
    $stmt = $pdo->prepare("
        SELECT 
            prompt_id, 
            model, 
            response_text, 
            total_duration, 
            eval_count, 
            eval_duration,
            prompt_eval_count, 
            prompt_eval_duration 
        FROM benchmark_results 
        WHERE model IN ($placeholders) AND success = 1
        ORDER BY prompt_id, model
    ");
    $stmt->execute($selectedModels);
    $results = $stmt->fetchAll();
    
    // Organize results by prompt_id and model
    $organizedResults = [];
    foreach ($results as $result) {
        $organizedResults[$result['prompt_id']][$result['model']] = $result;
    }
    
} catch (PDOException $e) {
    die("Database connection failed: " . $e->getMessage());
}

// HTML output
header('Content-Type: text/html; charset=utf-8');
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Benchmark Results Comparison</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            color: #333;
        }
        h1 {
            text-align: center;
            margin-bottom: 20px;
            color: #2c3e50;
        }
        .benchmark-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .benchmark-table th, .benchmark-table td {
            padding: 10px;
            border: 1px solid #ddd;
            vertical-align: top;
        }
        .benchmark-table th {
            background-color: #f5f5f5;
            font-weight: bold;
            text-align: left;
        }
        .benchmark-table tbody tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .benchmark-table tbody tr:hover {
            background-color: #f1f1f1;
        }
        .prompt-category {
            font-weight: bold;
            color: #7f8c8d;
        }
        .prompt-tags {
            font-size: 12px;
            color: #7f8c8d;
            margin-top: 5px;
        }
        .prompt-text {
            margin-top: 10px;
            padding: 10px;
            background-color: #ecf0f1;
            border-radius: 4px;
            font-family: monospace;
            white-space: pre-wrap;
        }
        .model-response {
            font-family: monospace;
            white-space: pre-wrap;
            padding: 10px;
            background-color: #f8f9fa;
            border-radius: 4px;
            margin-bottom: 10px;
            max-height: 300px;
            overflow-y: auto;
        }
        .metrics {
            font-size: 12px;
            color: #7f8c8d;
            margin-top: 5px;
        }
        .metrics span {
            display: inline-block;
            margin-right: 10px;
        }
        .filter-form {
            margin-bottom: 20px;
            padding: 15px;
            background-color: #f5f5f5;
            border-radius: 4px;
        }
        .filter-form label {
            margin-right: 10px;
        }
        .filter-form select {
            padding: 5px;
            margin-right: 10px;
        }
        .filter-form button {
            padding: 5px 10px;
            background-color: #3498db;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .filter-form button:hover {
            background-color: #2980b9;
        }
        .legend {
            margin-bottom: 20px;
            font-size: 14px;
        }
        .legend h3 {
            margin-bottom: 5px;
        }
        .legend div {
            margin-bottom: 5px;
        }
    </style>
</head>
<body>
    <h1>LLM Benchmark Results Comparison</h1>
    
    <div class="filter-form">
        <form method="GET">
            <label for="models">Select Models:</label>
            <select name="models" id="models" multiple>
                <?php 
                $allModels = $pdo->query("SELECT DISTINCT model FROM benchmark_results ORDER BY model")->fetchAll(PDO::FETCH_COLUMN);
                foreach ($allModels as $model) {
                    $selected = in_array($model, $selectedModels) ? 'selected' : '';
                    echo "<option value=\"" . htmlspecialchars($model) . "\" $selected>" . htmlspecialchars($model) . "</option>";
                }
                ?>
            </select>
            <button type="submit">Filter</button>
        </form>
    </div>

    <div class="legend">
        <h3>Metrics Legend:</h3>
        <div><strong>Total Duration:</strong> Total time taken for response generation (seconds)</div>
        <div><strong>Eval Count:</strong> Number of token evaluations performed</div>
        <div><strong>Eval Duration:</strong> Time spent on token evaluations (seconds)</div>
        <div><strong>Prompt Eval Count:</strong> Number of prompt token evaluations</div>
        <div><strong>Prompt Eval Duration:</strong> Time spent on prompt token evaluations (seconds)</div>
    </div>
    
    <table class="benchmark-table">
        <thead>
            <tr>
                <th>Prompt</th>
                <?php foreach ($selectedModels as $model): ?>
                    <th><?php echo htmlspecialchars($model); ?></th>
                <?php endforeach; ?>
            </tr>
        </thead>
        <tbody>
            <?php foreach ($prompts as $prompt): ?>
                <tr>
                    <td>
                        <div class="prompt-category"><?php echo htmlspecialchars($prompt['category']); ?></div>
                        <div class="prompt-tags">Tags: <?php echo htmlspecialchars($prompt['tags']); ?></div>
                        <div class="prompt-text"><?php echo htmlspecialchars($prompt['prompt_text']); ?></div>
                    </td>
                    
                    <?php foreach ($selectedModels as $model): ?>
                        <td>
                            <?php if (isset($organizedResults[$prompt['id']][$model])): ?>
                                <?php $result = $organizedResults[$prompt['id']][$model]; ?>
                                <div class="model-response"><?php echo htmlspecialchars($result['response_text']); ?></div>
                                <div class="metrics">
                                    <span><strong>Total Duration:</strong> <?php echo number_format($result['total_duration'], 3); ?>s</span>
                                    <span><strong>Eval Count:</strong> <?php echo $result['eval_count']; ?></span>
                                    <span><strong>Eval Duration:</strong> <?php echo number_format($result['eval_duration'], 3); ?>s</span>
                                    <span><strong>Prompt Eval Count:</strong> <?php echo $result['prompt_eval_count']; ?></span>
                                    <span><strong>Prompt Eval Duration:</strong> <?php echo number_format($result['prompt_eval_duration'], 3); ?>s</span>
                                </div>
                            <?php else: ?>
                                <div>No results available</div>
                            <?php endif; ?>
                        </td>
                    <?php endforeach; ?>
                </tr>
            <?php endforeach; ?>
        </tbody>
    </table>

    <script>
        // Convert multiple select to allow holding Ctrl/Cmd to select multiple
        document.addEventListener('DOMContentLoaded', function() {
            const modelSelect = document.getElementById('models');
            modelSelect.size = Math.min(10, modelSelect.options.length);
        });
    </script>
</body>
</html>