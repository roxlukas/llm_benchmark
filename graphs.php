<?php
/**
 * graphs.php
 * 
 * LLM Benchmark Results Comparison Graphs Generator
 * 
 * This script generates an HTML with graphs, comparing responses from different LLM models
 */

// Include configuration file
require_once 'config.php';

// Get category filter from GET parameter
$categoryFilter = isset($_GET['category']) ? trim($_GET['category']) : '';

function markdownToHtml($markdown, $smallHeaders = FALSE) {
    if ($smallHeaders === TRUE) {
        $h1 = '<div class="fw-bold">$1</div>';
        $h2 = $h1;
        $h3 = $h1;
        $h4 = $h1;
        $h5 = $h1;
    } else {
        $h1 = '<h1>$1</h1>';
        $h2 = '<h2>$1</h2>';
        $h3 = '<h3>$1</h3>';
        $h4 = '<h4>$1</h4>';
        $h5 = '<h4>$1</h4>';
    }
    // Nagłówki
    $markdown = preg_replace('/^# (.*?)$/m', $h1, $markdown);
    $markdown = preg_replace('/^## (.*?)$/m', $h2, $markdown);
    $markdown = preg_replace('/^### (.*?)$/m', $h3, $markdown);
    $markdown = preg_replace('/^#### (.*?)$/m', $h4, $markdown);
    $markdown = preg_replace('/^##### (.*?)$/m', $h5, $markdown);

    // Pogrubienie
    $markdown = preg_replace('/\*\*(.*?)\*\*/', '<strong>$1</strong>', $markdown);
    $markdown = preg_replace('/__(.*?)__/', '<strong>$1</strong>', $markdown);

    // Kursywa
    $markdown = preg_replace('/\*(.*?)\*/', '<em>$1</em>', $markdown);
    $markdown = preg_replace('/_(.*?)_/', '<em>$1</em>', $markdown);

    // Linki
    $markdown = preg_replace('/\[(.*?)\]\((.*?)\)/', '<a href="$2">$1</a>', $markdown);

    // Listy nienumerowane (grupowanie blokowe)
    $markdown = preg_replace_callback('/(?:^|\n)(?:- |\*) .*?(?=\n\n|\z)/s', function ($matches) {
        $items = preg_replace('/(?:^|\n)(?:- |\*) (.*?)(?=\n|$)/', '<li>$1</li>', $matches[0]);
        return "<ul>$items</ul>";
    }, $markdown);

    // Listy numerowane (grupowanie blokowe)
    $markdown = preg_replace_callback('/(?:^|\n)\d+\. .*?(?=\n\n|\z)/s', function ($matches) {
        $items = preg_replace('/(?:^|\n)\d+\. (.*?)(?=\n|$)/', '<li>$1</li>', $matches[0]);
        return "<ol>$items</ol>";
    }, $markdown);

    // Akapity
    $markdown = preg_replace('/\n\n/', '</p><p>', $markdown);
    $markdown = '<p>' . $markdown . '</p>';

    return trim($markdown);
}

try {
    // Connect to the database
    $pdo = getDatabaseConnection();
    
    // Get all unique categories for dropdown
    $categoryQuery = $pdo->query("SELECT DISTINCT category FROM prompts WHERE category IS NOT NULL AND category != '' ORDER BY category");
    $categories = $categoryQuery->fetchAll(PDO::FETCH_COLUMN);
    
    // Build WHERE clause for category filter
    $categoryWhereClause = '';
    $categoryParams = [];
    if (!empty($categoryFilter)) {
        $categoryWhereClause = 'WHERE p.category = :category';
        $categoryParams['category'] = $categoryFilter;
    }
    
    // Get all unique models (filtered by category if specified)
    $modelQuerySql = "SELECT DISTINCT br.model FROM benchmark_results br 
                      JOIN prompts p ON br.prompt_id = p.id 
                      $categoryWhereClause 
                      ORDER BY br.model";
    $modelQuery = $pdo->prepare($modelQuerySql);
    $modelQuery->execute($categoryParams);
    $models = $modelQuery->fetchAll(PDO::FETCH_COLUMN);
    
    // Get all prompts (filtered by category if specified)
    $promptQuerySql = "
        SELECT p.id, p.prompt_text, p.category 
        FROM prompts p 
        JOIN benchmark_results br ON p.id = br.prompt_id 
        $categoryWhereClause
        GROUP BY p.id
        ORDER BY p.id
    ";
    $promptQuery = $pdo->prepare($promptQuerySql);
    $promptQuery->execute($categoryParams);
    $prompts = $promptQuery->fetchAll(PDO::FETCH_ASSOC);
    
    // Get average durations and success rates by model (filtered by category if specified)
    $modelStatsQuerySql = "
        SELECT 
            br.model,
            mm.parameters, 
            AVG(br.total_duration) as avg_duration,
            AVG(br.eval_count) as avg_eval_count,
            COUNT(*) as total_runs,
            SUM(CASE WHEN br.success = 1 THEN 1 ELSE 0 END) as successful_runs,
            (SUM(CASE WHEN br.success = 1 THEN 1 ELSE 0 END) / COUNT(*)) * 100 as success_rate
        FROM benchmark_results br
        JOIN model_metadata mm ON br.model = mm.model_name
        JOIN prompts p ON br.prompt_id = p.id
        $categoryWhereClause
        GROUP BY br.model, mm.parameters
        ORDER BY avg_duration ASC
    ";
    $modelStatsQuery = $pdo->prepare($modelStatsQuerySql);
    $modelStatsQuery->execute($categoryParams);
    $modelStats = $modelStatsQuery->fetchAll(PDO::FETCH_ASSOC);
    
    // Get evaluation results by model (filtered by category if specified)
    $evaluationStatsQuerySql = "
        SELECT 
            br.model,
            mm.parameters,
            AVG(er.overall_score) as avg_overall_score,
            AVG(er.accuracy_score) as avg_accuracy_score,
            AVG(er.completeness_score) as avg_completeness_score,
            AVG(er.clarity_score) as avg_clarity_score,
            AVG(er.domain_expertise_score) as avg_domain_expertise_score,
            AVG(er.helpfulness_score) as avg_helpfulness_score,
            COUNT(er.id) as evaluation_count
        FROM evaluation_results er
        JOIN benchmark_results br ON er.benchmark_result_id = br.id
        JOIN model_metadata mm ON br.model = mm.model_name
        JOIN prompts p ON br.prompt_id = p.id
        $categoryWhereClause
        GROUP BY br.model, mm.parameters
        HAVING evaluation_count > 0
        ORDER BY avg_overall_score DESC
    ";
    $evaluationStatsQuery = $pdo->prepare($evaluationStatsQuerySql);
    $evaluationStatsQuery->execute($categoryParams);
    $evaluationStats = $evaluationStatsQuery->fetchAll(PDO::FETCH_ASSOC);
    
    // Get benchmark results per prompt
    $promptResults = [];
    foreach ($prompts as $prompt) {
        $resultQuery = $pdo->prepare("
            SELECT model, total_duration, success, response_text, error, mm.parameters
            FROM benchmark_results br
            JOIN model_metadata mm ON br.model = mm.model_name
            WHERE prompt_id = :promptId
            ORDER BY total_duration ASC
        ");
        $resultQuery->execute(['promptId' => $prompt['id']]);
        $promptResults[$prompt['id']] = $resultQuery->fetchAll(PDO::FETCH_ASSOC);
    }
    
} catch (PDOException $e) {
    die("Database connection failed: " . $e->getMessage());
}
?>

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Benchmark Visualization<?= !empty($categoryFilter) ? ' - ' . htmlspecialchars($categoryFilter) : '' ?></title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.3/jquery.min.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 20px;
            color: #333;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
        }
        h1, h2, h3 {
            color: #2c3e50;
        }
        .chart-container {
            height: 400px;
            margin-bottom: 20px;
        }
        .chart-container.large {
            height: 500px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 30px;
        }
        th, td {
            padding: 10px;
            border: 1px solid #ddd;
            text-align: left;
        }
        th {
            background-color: #f2f2f2;
            font-weight: bold;
            cursor: pointer;
        }
        th:hover {
            background-color: #e6e6e6;
        }
        th.sorted-asc::after {
            content: " ^";
        }
        th.sorted-desc::after {
            content: " ↓";
        }
        tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .success {
            color: green;
        }
        .failed {
            color: red;
        }
        .prompt-card {
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 20px;
            margin-bottom: 20px;
        }
        .prompt-text {
            background: #f5f7fa;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 15px;
            white-space: pre-wrap;
            font-family: monospace;
            max-height: 100px;
            overflow-y: auto;
        }
        .category-tag {
            display: inline-block;
            background: #3498db;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
            margin-bottom: 10px;
        }
        .toggle-response {
            background: #2980b9;
            color: white;
            border: none;
            padding: 5px 10px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
        }
        .toggle-response:hover {
            background: #3498db;
        }
        .response-container {
            display: none;
            margin-top: 10px;
        }
        .model-response {
            background: #f5f7fa;
            padding: 15px;
            border-radius: 5px;
            white-space: pre-wrap;
            font-family: monospace;
            max-height: 200px;
            overflow-y: auto;
            border-left: 3px solid #3498db;
        }
        .error-response {
            border-left: 3px solid #e74c3c;
        }
        .summary-table {
            margin-top: 10px;
        }
        .best-model {
            background-color: #e8f8f5 !important;
            font-weight: bold;
        }
        .evaluation-section {
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }
        .evaluation-section h2 {
            color: #27ae60;
            margin-top: 0;
        }
        .category-filter {
            background: #fff;
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            margin-bottom: 30px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        .category-filter h3 {
            margin-top: 0;
            color: #34495e;
        }
        .filter-form {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
        }
        .filter-form select {
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            min-width: 200px;
        }
        .filter-form button {
            background: #3498db;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }
        .filter-form button:hover {
            background: #2980b9;
        }
        .current-filter {
            background: #e8f6ff;
            padding: 10px;
            border-radius: 4px;
            margin-top: 10px;
            border-left: 3px solid #3498db;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>LLM Benchmark Visualization (<?=date("Y.m.d")?>)<br/><small>Lukasz Pozniak, <?=date("Y")?></small></h1>
        
        <!-- Category Filter Section -->
        <div class="category-filter">
            <h3>🔍 Filter by Category</h3>
            <form method="GET" class="filter-form">
                <label for="category">Category:</label>
                <select name="category" id="category">
                    <option value="">All Categories</option>
                    <?php foreach ($categories as $category): ?>
                        <option value="<?= htmlspecialchars($category) ?>" 
                                <?= $categoryFilter === $category ? 'selected' : '' ?>>
                            <?= htmlspecialchars($category) ?>
                        </option>
                    <?php endforeach; ?>
                </select>
                <button type="submit">Filter</button>
                <?php if (!empty($categoryFilter)): ?>
                    <a href="?" style="text-decoration: none;">
                        <button type="button">Clear Filter</button>
                    </a>
                <?php endif; ?>
            </form>
            
            <?php if (!empty($categoryFilter)): ?>
                <div class="current-filter">
                    <strong>Currently showing:</strong> <?= htmlspecialchars($categoryFilter) ?> 
                    (<?= count($prompts) ?> prompts)
                </div>
            <?php else: ?>
                <div class="current-filter">
                    <strong>Currently showing:</strong> All categories 
                    (<?= count($prompts) ?> prompts)
                </div>
            <?php endif; ?>
        </div>

        <?php if (empty($prompts)): ?>
            <div style="background: #fff3cd; padding: 20px; border-radius: 8px; border-left: 3px solid #ffc107; margin: 20px 0;">
                <strong>No results found</strong> for the selected category "<?= htmlspecialchars($categoryFilter) ?>".
                <br>Please try selecting a different category or <a href="?">view all categories</a>.
            </div>
        <?php else: ?>
    
        <?php if (!empty($evaluationStats)): ?>
        <div class="evaluation-section">
            <h2>🏆 Evaluation Results (Quality Assessment)<?= !empty($categoryFilter) ? ' - ' . htmlspecialchars($categoryFilter) : '' ?></h2>
            
            <h3>Overall Score by Model</h3>
            <div class="chart-container">
                <canvas id="overallScoreChart"></canvas>
            </div>
            
            <h3>Detailed Quality Metrics</h3>
            <div class="chart-container large">
                <canvas id="detailedMetricsChart"></canvas>
            </div>
            
            <h3>Evaluation Results Summary</h3>
            <table id="evaluationTable" class="summary-table">
                <thead>
                    <tr>
                        <th data-sort="rank">Rank</th>
                        <th data-sort="model">Model</th>
                        <th data-sort="params">Parameters</th>
                        <th data-sort="overall">Overall Score</th>
                        <th data-sort="accuracy">Accuracy</th>
                        <th data-sort="completeness">Completeness</th>
                        <th data-sort="clarity">Clarity</th>
                        <th data-sort="expertise">Domain Expertise</th>
                        <th data-sort="helpfulness">Helpfulness</th>
                        <th data-sort="count">Evaluations</th>
                    </tr>
                </thead>
                <tbody>
                    <?php 
                    $rank = 1;
                    foreach ($evaluationStats as $stat): 
                    ?>
                        <tr class="<?= $rank === 1 ? 'best-model' : '' ?>">
                            <td><?= $rank++ ?></td>
                            <td><?= htmlspecialchars($stat['model']) ?></td>
                            <td><?= htmlspecialchars($stat['parameters']) ?></td>
                            <td><?= number_format($stat['avg_overall_score'], 2) ?></td>
                            <td><?= number_format($stat['avg_accuracy_score'], 1) ?></td>
                            <td><?= number_format($stat['avg_completeness_score'], 1) ?></td>
                            <td><?= number_format($stat['avg_clarity_score'], 1) ?></td>
                            <td><?= number_format($stat['avg_domain_expertise_score'], 1) ?></td>
                            <td><?= number_format($stat['avg_helpfulness_score'], 1) ?></td>
                            <td><?= $stat['evaluation_count'] ?></td>
                        </tr>
                    <?php endforeach; ?>
                </tbody>
            </table>
        </div>
        <?php endif; ?>
        
        <h2>Overall Performance by Model<?= !empty($categoryFilter) ? ' - ' . htmlspecialchars($categoryFilter) : '' ?></h2>
        <div class="chart-container">
            <canvas id="overallChart"></canvas>
        </div>

        <h2>Success Rate by Model<?= !empty($categoryFilter) ? ' - ' . htmlspecialchars($categoryFilter) : '' ?></h2>
        <div class="chart-container">
            <canvas id="successRateChart"></canvas>
        </div>
        
        <h3>Model Performance Summary</h3>
        <table id="summaryTable" class="summary-table">
            <thead>
                <tr>
                    <th data-sort="rank">Rank</th>
                    <th data-sort="model">Model</th>
                    <th data-sort="params">Parameters</th>
                    <th data-sort="duration">Avg Duration (s)</th>
                    <th data-sort="evalcount">Avg Output Tokens</th>
                    <th data-sort="success">Success Rate (%)</th>
                    <th data-sort="runs">Total Runs</th>
                </tr>
            </thead>
            <tbody>
                <?php 
                $rank = 1;
                foreach ($modelStats as $stat): 
                ?>
                    <tr class="<?= $rank === 1 ? 'best-model' : '' ?>">
                        <td><?= $rank++ ?></td>
                        <td><?= htmlspecialchars($stat['model']) ?></td>
                        <td><?= htmlspecialchars($stat['parameters']) ?></td>
                        <td><?= number_format($stat['avg_duration'], 4) ?></td>
                        <td><?= number_format($stat['avg_eval_count'], 0) ?></td>
                        <td><?= number_format($stat['success_rate'], 1) ?></td>
                        <td><?= $stat['total_runs'] ?></td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>

        <h2>Results by Prompt<?= !empty($categoryFilter) ? ' - ' . htmlspecialchars($categoryFilter) : '' ?></h2>
        <?php foreach ($prompts as $prompt): ?>
            <div class="prompt-card">
                <?php if (!empty($prompt['category'])): ?>
                    <span class="category-tag"><?= htmlspecialchars($prompt['category']) ?></span>
                <?php endif; ?>
                
                <h3>Prompt #<?= $prompt['id'] ?></h3>
                <div class="prompt-text"><?= htmlspecialchars($prompt['prompt_text']) ?></div>
                
                <table>
                    <thead>
                        <tr>
                            <th>Rank</th>
                            <th>Model</th>
                            <th>Parameters</th>
                            <th>Total Duration (s)</th>
                            <th>Status</th>
                            <th>Response</th>
                        </tr>
                    </thead>
                    <tbody>
                        <?php 
                        $rank = 1;
                        foreach ($promptResults[$prompt['id']] as $result): 
                            $responseId = "response-" . $prompt['id'] . "-" . $rank;
                        ?>
                            <tr>
                                <td><?= $rank ?></td>
                                <td><?= htmlspecialchars($result['model']) ?></td>
                                <td><?= htmlspecialchars($result['parameters']) ?></td>
                                <td><?= number_format($result['total_duration'], 4) ?></td>
                                <td class="<?= $result['success'] ? 'success' : 'failed' ?>">
                                    <?= $result['success'] ? 'Success' : 'Failed' ?>
                                </td>
                                <td>
                                    <button class="toggle-response" data-target="<?= $responseId ?>">
                                        Show Response
                                    </button>
                                    <div id="<?= $responseId ?>" class="response-container">
                                        <?php if ($result['success']): ?>
                                            <div class="model-response">
                                                <?= markdownToHtml(htmlspecialchars($result['response_text'])) ?>
                                            </div>
                                        <?php else: ?>
                                            <div class="model-response error-response">
                                                Error: <?= htmlspecialchars($result['error']) ?>
                                            </div>
                                        <?php endif; ?>
                                    </div>
                                </td>
                            </tr>
                        <?php 
                            $rank++;
                        endforeach; 
                        ?>
                    </tbody>
                </table>
            </div>
        <?php endforeach; ?>
        
        <?php endif; ?>
    </div>

    <script>
        <?php if (!empty($modelStats)): ?>
        // Prepare data for the overall chart
        const models = <?= json_encode(array_column($modelStats, 'model')) ?>;
        const durations = <?= json_encode(array_column($modelStats, 'avg_duration')) ?>;
        
        // Create the overall chart
        const ctx = document.getElementById('overallChart').getContext('2d');
        const overallChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: models,
                datasets: [{
                    label: 'Average Total Duration (s)',
                    data: durations,
                    backgroundColor: 'rgba(54, 162, 235, 0.6)',
                    borderColor: 'rgba(54, 162, 235, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Duration (seconds)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Model'
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Average Total Duration by Model<?= !empty($categoryFilter) ? ' - ' . addslashes($categoryFilter) : '' ?>',
                        font: {
                            size: 16
                        }
                    },
                    legend: {
                        position: 'top',
                    }
                }
            }
        });

        // Prepare data for the success rate chart
        const successRates = <?= json_encode(array_column($modelStats, 'success_rate')) ?>;

        // Create the success rate chart
        const ctxSuccess = document.getElementById('successRateChart').getContext('2d');
        const successRateChart = new Chart(ctxSuccess, {
            type: 'bar',
            data: {
                labels: models,
                datasets: [{
                    label: 'Success Rate (%)',
                    data: successRates,
                    backgroundColor: 'rgba(75, 192, 192, 0.6)',
                    borderColor: 'rgba(75, 192, 192, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        title: {
                            display: true,
                            text: 'Success Rate (%)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Model'
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Success Rate by Model<?= !empty($categoryFilter) ? ' - ' . addslashes($categoryFilter) : '' ?>',
                        font: {
                            size: 16
                        }
                    },
                    legend: {
                        position: 'top',
                    }
                }
            }
        });
        <?php endif; ?>

        <?php if (!empty($evaluationStats)): ?>
        // Evaluation charts data
        const evalModels = <?= json_encode(array_column($evaluationStats, 'model')) ?>;
        const overallScores = <?= json_encode(array_column($evaluationStats, 'avg_overall_score')) ?>;
        const accuracyScores = <?= json_encode(array_column($evaluationStats, 'avg_accuracy_score')) ?>;
        const completenessScores = <?= json_encode(array_column($evaluationStats, 'avg_completeness_score')) ?>;
        const clarityScores = <?= json_encode(array_column($evaluationStats, 'avg_clarity_score')) ?>;
        const expertiseScores = <?= json_encode(array_column($evaluationStats, 'avg_domain_expertise_score')) ?>;
        const helpfulnessScores = <?= json_encode(array_column($evaluationStats, 'avg_helpfulness_score')) ?>;

        // Create overall score chart
        const ctxOverallScore = document.getElementById('overallScoreChart').getContext('2d');
        const overallScoreChart = new Chart(ctxOverallScore, {
            type: 'bar',
            data: {
                labels: evalModels,
                datasets: [{
                    label: 'Overall Score',
                    data: overallScores,
                    backgroundColor: 'rgba(46, 204, 113, 0.6)',
                    borderColor: 'rgba(46, 204, 113, 1)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 10,
                        title: {
                            display: true,
                            text: 'Score (0-10)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Model'
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Overall Quality Score by Model (Best to Worst)<?= !empty($categoryFilter) ? ' - ' . addslashes($categoryFilter) : '' ?>',
                        font: {
                            size: 16
                        }
                    },
                    legend: {
                        position: 'top',
                    }
                }
            }
        });

        // Create detailed metrics chart
        const ctxDetailed = document.getElementById('detailedMetricsChart').getContext('2d');
        const detailedMetricsChart = new Chart(ctxDetailed, {
            type: 'bar',
            data: {
                labels: evalModels,
                datasets: [
                    {
                        label: 'Accuracy',
                        data: accuracyScores,
                        backgroundColor: 'rgba(231, 76, 60, 0.6)',
                        borderColor: 'rgba(231, 76, 60, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Completeness',
                        data: completenessScores,
                        backgroundColor: 'rgba(52, 152, 219, 0.6)',
                        borderColor: 'rgba(52, 152, 219, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Clarity',
                        data: clarityScores,
                        backgroundColor: 'rgba(155, 89, 182, 0.6)',
                        borderColor: 'rgba(155, 89, 182, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Domain Expertise',
                        data: expertiseScores,
                        backgroundColor: 'rgba(241, 196, 15, 0.6)',
                        borderColor: 'rgba(241, 196, 15, 1)',
                        borderWidth: 1
                    },
                    {
                        label: 'Helpfulness',
                        data: helpfulnessScores,
                        backgroundColor: 'rgba(26, 188, 156, 0.6)',
                        borderColor: 'rgba(26, 188, 156, 1)',
                        borderWidth: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 10,
                        title: {
                            display: true,
                            text: 'Score (1-10)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Model'
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Detailed Quality Metrics by Model<?= !empty($categoryFilter) ? ' - ' . addslashes($categoryFilter) : '' ?>',
                        font: {
                            size: 16
                        }
                    },
                    legend: {
                        position: 'top',
                    }
                }
            }
        });
        <?php endif; ?>
        
        // Toggle response visibility
        document.querySelectorAll('.toggle-response').forEach(button => {
            button.addEventListener('click', function() {
                const targetId = this.getAttribute('data-target');
                const responseContainer = document.getElementById(targetId);
                
                if (responseContainer.style.display === 'block') {
                    responseContainer.style.display = 'none';
                    this.textContent = 'Show Response';
                } else {
                    responseContainer.style.display = 'block';
                    this.textContent = 'Hide Response';
                }
            });
        });
        
        // Add sorting functionality to summary table
        document.querySelectorAll('#summaryTable th, #evaluationTable th').forEach(header => {
            header.addEventListener('click', function() {
                const table = this.closest('table');
                const tbody = table.querySelector('tbody');
                const rows = Array.from(tbody.querySelectorAll('tr'));
                const column = this.cellIndex;
                const sortKey = this.getAttribute('data-sort');
                
                // Clear previous sort indicators
                table.querySelectorAll('th').forEach(th => {
                    th.classList.remove('sorted-asc', 'sorted-desc');
                });
                
                // Check if we're reversing the current sort
                const isAscending = this.classList.contains('sorted-desc') || 
                                   (!this.classList.contains('sorted-asc') && sortKey !== 'rank');
                
                // Add sort indicator
                this.classList.add(isAscending ? 'sorted-asc' : 'sorted-desc');
                
                // Sort the rows
                rows.sort((rowA, rowB) => {
                    let valueA = rowA.cells[column].textContent.trim();
                    let valueB = rowB.cells[column].textContent.trim();
                    
                    // Handle numeric values
                    if (['rank', 'duration', 'success', 'runs', 'overall', 'accuracy', 'completeness', 'clarity', 'expertise', 'helpfulness', 'count'].includes(sortKey)) {
                        valueA = parseFloat(valueA.replace(',', ''));
                        valueB = parseFloat(valueB.replace(',', ''));
                    }
                    
                    if (valueA < valueB) return isAscending ? -1 : 1;
                    if (valueA > valueB) return isAscending ? 1 : -1;
                    return 0;
                });
                
                // Reorder the rows
                rows.forEach(row => tbody.appendChild(row));
                
                // Update ranks if needed
                if (sortKey !== 'rank') {
                    rows.forEach((row, index) => {
                        row.cells[0].textContent = index + 1;
                        
                        // Mark best model
                        rows.forEach(r => r.classList.remove('best-model'));
                        rows[0].classList.add('best-model');
                    });
                }
            });
        });
    </script>
</body>
</html>