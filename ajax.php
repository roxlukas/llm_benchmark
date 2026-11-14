<?php
/**
 * AJAX handler for the human thumbs up/down rating (benchmark_results.human_rating).
 * 'success' only says whether the model returned an answer; the rating no longer touches it.
 */

// Only process POST requests
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    echo json_encode(['success' => false, 'message' => 'Invalid request method']);
    exit;
}

// Check if required parameters are present
if (!isset($_POST['id']) || !isset($_POST['rating'])) {
    echo json_encode(['success' => false, 'message' => 'Missing required parameters']);
    exit;
}

// Validate the parameters
$id = filter_var($_POST['id'], FILTER_VALIDATE_INT);
$rating = filter_var($_POST['rating'], FILTER_VALIDATE_INT);

if ($id === false || ($rating !== 0 && $rating !== 1)) {
    echo json_encode(['success' => false, 'message' => 'Invalid parameter values']);
    exit;
}

// Include configuration file
require_once 'config.php';

try {
    // Connect to the database
    $pdo = getDatabaseConnection();

    // Prepare and execute the update query
    $stmt = $pdo->prepare("UPDATE benchmark_results SET human_rating = :rating WHERE id = :id");
    $result = $stmt->execute([
        ':id' => $id,
        ':rating' => $rating
    ]);

    if ($result) {
        // rowCount() is 0 when the rating did not change, so check that the row exists instead
        $check = $pdo->prepare("SELECT 1 FROM benchmark_results WHERE id = :id");
        $check->execute([':id' => $id]);
        if ($check->fetchColumn()) {
            echo json_encode(['success' => true, 'message' => 'Rating updated successfully']);
        } else {
            echo json_encode(['success' => false, 'message' => 'No record found with the provided ID']);
        }
    } else {
        echo json_encode(['success' => false, 'message' => 'Failed to update rating']);
    }

} catch (PDOException $e) {
    echo json_encode(['success' => false, 'message' => 'Database error: ' . $e->getMessage()]);
    exit;
}
