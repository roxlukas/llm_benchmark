<?php
/**
 * index.php
 * 
 * LLM Benchmark Results Comparison Table Generator
 * 
 * This script generates an HTML table comparing responses from different LLM models
 * with the original prompts, timing information, and external LLM evaluation scores.
 */

// Include configuration file
require_once 'config.php';

// Get models to include from GET parameters, or use all models if not specified
$selectedModels = isset($_GET['models']) ? explode(',', $_GET['models']) : [];

// Connect to the database
try {
    $pdo = getDatabaseConnection();
    
    // Get all available models if none specified
    if (empty($selectedModels)) {
        $stmt = $pdo->query("SELECT DISTINCT model FROM benchmark_results ORDER BY model");
        $selectedModels = $stmt->fetchAll(PDO::FETCH_COLUMN);
    }
    
    // Get all prompts
    $stmt = $pdo->query("SELECT id, prompt_text, category, tags, created_at, `goldenAnswer` FROM prompts ORDER BY category, id");
    $prompts = $stmt->fetchAll();
    
    // Get all results for the selected models
    $placeholders = implode(',', array_fill(0, count($selectedModels), '?'));

    // Get model metadata
    $modelMetadata = [];
    $stmt = $pdo->prepare("SELECT * FROM model_metadata WHERE model_name IN ($placeholders)");
    $stmt->execute($selectedModels);
    $modelMetadataResults = $stmt->fetchAll();

    foreach ($modelMetadataResults as $metadata) {
        $modelMetadata[$metadata['model_name']] = $metadata;
    }

    // Get benchmark results with evaluation scores
    $stmt = $pdo->prepare("
    SELECT 
        br.id,
        prompt_id, 
        br.model, 
        response_text,
        br.success,
        total_duration, 
        eval_count, 
        eval_duration,
        prompt_eval_count, 
        prompt_eval_duration,
        mm.parameters,
        mm.architecture,
        mm.context_length,
        mm.quantization,
        er.accuracy_score,
        er.accuracy_justification,
        er.completeness_score,
        er.completeness_justification,
        er.clarity_score,
        er.clarity_justification,
        er.domain_expertise_score,
        er.domain_expertise_justification,
        er.helpfulness_score,
        er.helpfulness_justification,
        er.overall_score,
        er.overall_assessment
    FROM benchmark_results br
    LEFT JOIN model_metadata mm ON br.model = mm.model_name
    LEFT JOIN evaluation_results er ON br.id = er.benchmark_result_id
    WHERE br.model IN ($placeholders)
    ORDER BY prompt_id, br.model
    ");
    $stmt->execute($selectedModels);
    $results = $stmt->fetchAll();

    $stmt = $pdo->prepare("SELECT SUM(total_duration) FROM `benchmark_results` WHERE 1");
    $stmt->execute();
    $total_time_raw = $stmt->fetchAll();
    $total_time = $total_time_raw[0]['SUM(total_duration)'];
    
    // Organize results by prompt_id and model
    $organizedResults = [];
    foreach ($results as $result) {
        $organizedResults[$result['prompt_id']][$result['model']] = $result;
    }
    
} catch (PDOException $e) {
    die("Database connection failed: " . $e->getMessage());
}

// Generate a unique filename for CSS
$cssFilename = 'benchmark_styles_' . date('YmdHis') . '.css';
$cssContent = <<<CSS
body {
    font-family: Arial, sans-serif;
    line-height: 1.5;
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
.model-header-row th {
    vertical-align: middle;
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
    max-height: 300px;
    overflow-y: auto;
    width: 320px;
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
    width: 240px;
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
.table-with-sticky-header {
  width: 100%;
  border-collapse: collapse;
}

.table-with-sticky-header thead tr {
  position: -webkit-sticky; /* For Safari */
  position: sticky;
  top: 0;
  background-color: white; /* Or any color for your header */
  z-index: 10;
}

/* Optional styling */
.table-with-sticky-header th, .table-with-sticky-header td {
  padding: 10px;
  border: 1px solid #ddd;
}

.model-header-metadata {
    font-size: 12px;
    color: #34495e;
    background-color: #f0f3f4;
    padding: 5px;
    text-align: left;
}
.model-header-metadata div {
    margin: 3px 0;
}
.benchmark-table th {
    text-align: center;
}

/* Thumbs up and down styling */
.response-rating {
    margin-top: 10px;
    display: flex;
    justify-content: flex-end;
}
.rating-btn {
    cursor: pointer;
    margin-left: 10px;
    padding: 5px;
    border: none;
    background-color: transparent;
    font-size: 18px;
    transition: transform 0.2s;
}
.rating-btn:hover {
    transform: scale(1.2);
}
.thumbs-up {
    color: #2ecc71;
}
.thumbs-down {
    color: #e74c3c;
}
.rating-btn.selected {
    opacity: 1;
    transform: scale(1.2);
}
.rating-btn.not-selected {
    opacity: 0.33;
}
.rating-status {
    font-size: 12px;
    margin-top: 5px;
    text-align: right;
    color: #7f8c8d;
}

/* Evaluation scores styling */
.evaluation-scores {
    margin-top: 10px;
    padding: 8px;
    background-color: #f0f8ff;
    border-radius: 4px;
    font-size: 12px;
    font-weight: bold;
}

.score-item {
    display: inline-block;
    margin: 2px 4px;
    padding: 2px 6px;
    background-color: #e8f4fd;
    border-radius: 3px;
    cursor: help;
    position: relative;
}

.score-item:hover {
    background-color: #b0b0b0;
}

.score-5 {
    background-color: #009600;
    color: #ffffff;
}
.score-4 {
    background-color: #00CC00;
    color: #ffffff;
}
.score-3 {
    background-color: #dddd00;
    color: #2c3e50;
}
.score-2 {
    background-color: #dd9600;
    color: #ffffff;
}
.score-1 {
    background-color: #dd0000;
    color: #ffffff;
}

.score-5:hover {
    background-color: #00bb00;
    color: #ffffff;
}
.score-4:hover {
    background-color: #00ee00;
    color: #ffffff;
}
.score-3:hover {
    background-color: #ffff00;
    color: #2c3e50;
}
.score-2:hover {
    background-color: #ffbb00;
    color: #ffffff;
}
.score-1:hover {
    background-color: #ff3333;
    color: #ffffff;
}

/* Tooltip styling */
.tooltip {
    position: absolute;
    background-color: #333;
    color: white;
    padding: 8px 12px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: normal;
    white-space: normal;
    width: 300px;
    max-width: 300px;
    z-index: 1000;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.3s, visibility 0.3s;
    pointer-events: none;
    top: -10px;
    left: 50%;
    transform: translateX(-50%) translateY(-100%);
}

.tooltip::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    margin-left: -5px;
    border: 5px solid transparent;
    border-top-color: #333;
}

.score-item:hover .tooltip {
    opacity: 1;
    visibility: visible;
}

.overall-score {
    font-weight: bold;
    border-right: 3px solid #444444;
    border-bottom: 3px solid #444444;
}

.no-evaluation {
    color: #95a5a6;
    font-style: italic;
}
CSS;

// HTML output
header('Content-Type: text/html; charset=utf-8');
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LLM Benchmark Results Comparison</title>
    <link rel="stylesheet" href="<?php echo htmlspecialchars($cssFilename); ?>">
    <style><?=$cssContent?></style>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
</head>
<body>
    <h1>LLM Benchmark Results Comparison (<?=date("Y.m.d")?>)<br/><small>Lukasz Pozniak, <?=date("Y")?></small></h1>
    
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

    <div class="legend" style="float: left; width: 50%;">
        <h3>Metrics Legend:</h3>
        <div><strong>Total Duration:</strong> Total time taken for response generation (seconds)</div>
        <div><strong>Eval Count:</strong> Number of token evaluations performed</div>
        <div><strong>Eval Duration:</strong> Time spent on token evaluations (seconds)</div>
        <div><strong>Prompt Eval Count:</strong> Number of prompt token evaluations</div>
        <div><strong>Prompt Eval Duration:</strong> Time spent on prompt token evaluations (seconds)</div>
        <div><strong>Evaluation Scores:</strong> AVG (Overall Average), Acc (Accuracy), Cmpl (Completeness), Clear (Clarity), Exprt (Domain Expertise), Help (Helpfulness)</div>
    </div>
    
    <div class="legend" style="float: right; width: 50%;">
        <h3>Hardware:</h3>
        <div><strong>CPU:</strong> Intel i5-11400F "Rocket Lake" 6C, 12T 2.60 GHz (4.40 GHz Turbo)</div>
        <div><strong>RAM:</strong> 64 GB DDR4 3200 MT/s</div>
        <div><strong>GPU:</strong> Gigabyte GeForce RTX 2070 OC 8G</div>
        <div><strong>VRAM:</strong> 8 GB GDDR6</div>
        <div><strong>Total GPU time spent:</strong> <?php echo(number_format($total_time / 3600, 2)); ?>hr</div>
        <div><strong>Total Power spent:</strong> <?php echo(number_format((0.1 + 0.187) * ($total_time / 3600), 2)); ?>kWh (<?php echo(number_format(0.6262 * (0.09 + 0.187) * ($total_time / 3600), 2)); ?> PLN)</div>
    </div>
    
    <table class="benchmark-table table-with-sticky-header">
        <thead>
            <tr class="model-header-row">
            <th>Prompt</th>
                <?php foreach ($selectedModels as $model): ?>
                    <th>
                            <div><strong><?php echo htmlspecialchars($model); ?></strong></div>
                            <small>
                            <div><strong>Arch:</strong> <?php 
                                echo htmlspecialchars($modelMetadata[$model]['architecture'] ?? 'N/A'); 
                            ?></div>
                            <div><strong>Params:</strong> <?php 
                                echo htmlspecialchars($modelMetadata[$model]['parameters'] ?? 'N/A'); 
                            ?></div>
                            <div><strong>Context:</strong> <?php 
                                echo ($modelMetadata[$model]['context_length'] ?? 'N/A') . ' tokens'; 
                            ?></div>
                            <div><strong>Quant:</strong> <?php 
                                echo htmlspecialchars($modelMetadata[$model]['quantization'] ?? 'N/A'); 
                            ?></div></small>
                    </th>
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
                        <div class="prompt-tags">Added: <?php echo htmlspecialchars($prompt['created_at']); ?></div>
                        <div class="prompt-tags">"Golden" answer:</div>
                        <div class="prompt-text"><?php echo htmlspecialchars($prompt['goldenAnswer']); ?></div>
                    </td>
                    
                    <?php foreach ($selectedModels as $model): ?>
                        <td>
                            <?php if (isset($organizedResults[$prompt['id']][$model])): ?>
                                <?php 
                                $result = $organizedResults[$prompt['id']][$model]; 
                                if ($result['eval_duration'] > 1000000) $result['eval_duration'] = $result['eval_duration'] / 1000000000;
                                if ($result['prompt_eval_duration'] > 1000000) $result['prompt_eval_duration'] = $result['prompt_eval_duration'] / 1000000000;
                                ?>
                                <div class="model-response"><?php echo htmlspecialchars($result['response_text']); ?></div>
                                
                                <?php if (!is_null($result['overall_score'])): ?>
                                    <!-- Evaluation Scores -->
                                    <div class="evaluation-scores">
                                        <span class="score-item overall-score score-<?=floor($result['overall_score'])?>">
                                            AVG: <?php echo number_format($result['overall_score'], 1); ?>
                                            <div class="tooltip">
                                                <?php echo htmlspecialchars($result['overall_assessment'] ?? 'No overall assessment provided'); ?>
                                            </div>
                                        </span>
                                        
                                        <?php if (!is_null($result['accuracy_score'])): ?>
                                            <span class="score-item score-<?=floor($result['accuracy_score'])?>">
                                                Acc: <?php echo $result['accuracy_score']; ?>
                                                <div class="tooltip">
                                                    <strong>Accuracy:</strong> <?php echo htmlspecialchars($result['accuracy_justification'] ?? 'No justification provided'); ?>
                                                </div>
                                            </span>
                                        <?php endif; ?>
                                        
                                        <?php if (!is_null($result['completeness_score'])): ?>
                                            <span class="score-item score-<?=floor($result['completeness_score'])?>">
                                                Cmpl: <?php echo $result['completeness_score']; ?>
                                                <div class="tooltip">
                                                    <strong>Completeness:</strong> <?php echo htmlspecialchars($result['completeness_justification'] ?? 'No justification provided'); ?>
                                                </div>
                                            </span>
                                        <?php endif; ?>
                                        
                                        <?php if (!is_null($result['clarity_score'])): ?>
                                            <span class="score-item score-<?=floor($result['clarity_score'])?>">
                                                Clear: <?php echo $result['clarity_score']; ?>
                                                <div class="tooltip">
                                                    <strong>Clarity:</strong> <?php echo htmlspecialchars($result['clarity_justification'] ?? 'No justification provided'); ?>
                                                </div>
                                            </span>
                                        <?php endif; ?>
                                        
                                        <?php if (!is_null($result['domain_expertise_score'])): ?>
                                            <span class="score-item score-<?=floor($result['domain_expertise_score'])?>">
                                                Exprt: <?php echo $result['domain_expertise_score']; ?>
                                                <div class="tooltip">
                                                    <strong>Domain Expertise:</strong> <?php echo htmlspecialchars($result['domain_expertise_justification'] ?? 'No justification provided'); ?>
                                                </div>
                                            </span>
                                        <?php endif; ?>
                                        
                                        <?php if (!is_null($result['helpfulness_score'])): ?>
                                            <span class="score-item score-<?=floor($result['helpfulness_score'])?>">
                                                Help: <?php echo $result['helpfulness_score']; ?>
                                                <div class="tooltip">
                                                    <strong>Helpfulness:</strong> <?php echo htmlspecialchars($result['helpfulness_justification'] ?? 'No justification provided'); ?>
                                                </div>
                                            </span>
                                        <?php endif; ?>
                                        <?php 
                                                if ($result['success'] == 1) {
                                                    $human_rating = 'Good';
                                                    $human_style = 'score-5';
                                                } else if ($result['success'] == 0) {
                                                    $human_rating = 'Bad';
                                                    $human_style = 'score-1';
                                                } else {
                                                    $human_rating = 'Not rated yet';
                                                    $human_style = '';
                                                }
                                                ?>
                                        <span class="score-item <?=$human_style?>">
                                            Human rating: <?=$human_rating?>
                                        </span>
                                    </div>
                                <?php else: ?>
                                    <div class="evaluation-scores no-evaluation">
                                        No evaluation available
                                    </div>
                                <?php endif; ?>
                                
                                <div class="metrics">
                                    <span><strong>Total Duration:</strong> <?php echo number_format($result['total_duration'], 3); ?>s</span>
                                    <span><strong>Eval Count:</strong> <?php echo $result['eval_count']; ?> (<?php echo number_format($result['eval_count']/$result['eval_duration'], 2); ?> token/s)</span>
                                    <span><strong>Eval Duration:</strong> <?php echo number_format($result['eval_duration'], 3); ?>s</span>
                                    <span><strong>Prompt Eval Count:</strong> <?php echo $result['prompt_eval_count']; ?></span>
                                    <span><strong>Prompt Eval Duration:</strong> <?php echo number_format($result['prompt_eval_duration'], 3); ?>s</span>
                                </div>
                                
                                <!-- Rating buttons -->
                                <div class="response-rating" data-response-id="<?php echo $result['id']; ?>">
                                    <button class="rating-btn thumbs-up <?php echo ($result['success'] == 1) ? 'selected' : 'not-selected'; ?>" 
                                            data-value="1" aria-label="Thumbs up">
                                        <i class="fas fa-thumbs-up"></i>
                                    </button>
                                    <button class="rating-btn thumbs-down <?php echo ($result['success'] == 0) ? 'selected' : 'not-selected'; ?>" 
                                            data-value="0" aria-label="Thumbs down">
                                        <i class="fas fa-thumbs-down"></i>
                                    </button>
                                </div>
                                <div class="rating-status" id="status-<?php echo $result['id']; ?>">
                                    <?php 
                                    /*if ($result['success'] == 1) {
                                        echo 'Rated: Good';
                                    } else if ($result['success'] == 0) {
                                        echo 'Rated: Bad';
                                    } else {
                                        echo 'Not rated yet';
                                    }*/
                                    ?>
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
        
        document.addEventListener('DOMContentLoaded', function() {
            const tableHeader = document.querySelector('.table-with-sticky-header thead');
            const tableTop = document.querySelector('.table-with-sticky-header').offsetTop;
            
            function handleScroll() {
                const scrollY = window.scrollY;
                
                // When user scrolls past the table's top position, add sticky class
                if (scrollY >= tableTop && !tableHeader.classList.contains('is-sticky')) {
                tableHeader.classList.add('is-sticky');
                } 
                // When user scrolls back up above the table, remove sticky class
                else if (scrollY < tableTop && tableHeader.classList.contains('is-sticky')) {
                tableHeader.classList.remove('is-sticky');
                }
            }
            
            window.addEventListener('scroll', handleScroll);
            
            // Rating buttons functionality
            const ratingButtons = document.querySelectorAll('.rating-btn');
            
            ratingButtons.forEach(btn => {
                btn.addEventListener('click', function() {
                    const ratingContainer = this.closest('.response-rating');
                    const responseId = ratingContainer.dataset.responseId;
                    const value = this.dataset.value;
                    const statusElement = document.getElementById(`status-${responseId}`);
                    
                    // Update UI immediately for better UX
                    const thumbsUp = ratingContainer.querySelector('.thumbs-up');
                    const thumbsDown = ratingContainer.querySelector('.thumbs-down');
                    
                    thumbsUp.classList.remove('selected', 'not-selected');
                    thumbsDown.classList.remove('selected', 'not-selected');
                    
                    if (value === '1') {
                        thumbsUp.classList.add('selected');
                        thumbsDown.classList.add('not-selected');
                        statusElement.textContent = 'Rated: Good';
                    } else {
                        thumbsDown.classList.add('selected');
                        thumbsUp.classList.add('not-selected');
                        statusElement.textContent = 'Rated: Bad';
                    }
                    
                    // Send AJAX request to update database
                    const xhr = new XMLHttpRequest();
                    xhr.open('POST', 'ajax.php', true);
                    xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded');
                    xhr.onreadystatechange = function() {
                        if (xhr.readyState === 4) {
                            if (xhr.status === 200) {
                                const response = JSON.parse(xhr.responseText);
                                if (response.success) {
                                    statusElement.textContent = value === '1' ? 'Rating saved: Good' : 'Rating saved: Bad';
                                } else {
                                    statusElement.textContent = 'Error: ' + response.message;
                                }
                            } else {
                                statusElement.textContent = 'Error updating rating';
                            }
                        }
                    };
                    xhr.send(`id=${responseId}&success=${value}`);
                });
            });
        });
    </script>
</body>
</html>