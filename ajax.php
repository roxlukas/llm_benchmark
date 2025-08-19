<?php
/**
 * AJAX handler for updating benchmark_results 'success' field
 * Processes thumbs up/down rating submissions
 */

// Only process POST requests
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    echo json_encode(['success' => false, 'message' => 'Invalid request method']);
    exit;
}

// Check if required parameters are present
if (!isset($_POST['id']) || !isset($_POST['success'])) {
    echo json_encode(['success' => false, 'message' => 'Missing required parameters']);
    exit;
}

// Validate the parameters
$id = filter_var($_POST['id'], FILTER_VALIDATE_INT);
$success = filter_var($_POST['success'], FILTER_VALIDATE_INT);

if ($id === false || ($success !== 0 && $success !== 1)) {
    echo json_encode(['success' => false, 'message' => 'Invalid parameter values']);
    exit;
}

// Include configuration file
require_once 'config.php';

try {
    // Connect to the database
    $pdo = getDatabaseConnection();
    
    // Prepare and execute the update query
    $stmt = $pdo->prepare("UPDATE benchmark_results SET success = :success WHERE id = :id");
    $result = $stmt->execute([
        ':id' => $id,
        ':success' => $success
    ]);
    
    if ($result) {
        // Check if any rows were affected
        if ($stmt->rowCount() > 0) {
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
