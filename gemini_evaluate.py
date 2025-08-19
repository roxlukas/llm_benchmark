# LLM Response Evaluator using Gemini API
# To run this code you need to install the following dependencies:
# pip install google-genai mysql-connector-python python-dotenv

import argparse
import json
import mysql.connector
from mysql.connector import Error
from google import genai
from google.genai import types
import time
from datetime import datetime
import sys
import os
from dotenv import load_dotenv

class LLMEvaluator:
    def __init__(self, db_config, gemini_api_key):
        self.db_config = db_config
        self.gemini_client = genai.Client(api_key=gemini_api_key)
        self.model = "gemini-2.5-flash-preview-05-20"
    
    def connect_to_database(self):
        """Establish connection to MySQL database"""
        try:
            connection = mysql.connector.connect(**self.db_config)
            if connection.is_connected():
                print(f"Successfully connected to MySQL database: {self.db_config['database']}")
                return connection
        except Error as e:
            print(f"Error connecting to MySQL database: {e}")
            return None
    
    def get_unevaluated_responses(self, connection):
        """Fetch responses that haven't been evaluated yet"""
        try:
            cursor = connection.cursor(dictionary=True)
            # First, check if evaluation table exists, if not create it
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS evaluation_results (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    benchmark_result_id INT NOT NULL,
                    accuracy_score INT,
                    accuracy_justification TEXT,
                    completeness_score INT,
                    completeness_justification TEXT,
                    clarity_score INT,
                    clarity_justification TEXT,
                    domain_expertise_score INT,
                    domain_expertise_justification TEXT,
                    helpfulness_score INT,
                    helpfulness_justification TEXT,
                    overall_score DECIMAL(3,2),
                    overall_assessment TEXT,
                    key_strengths JSON,
                    key_weaknesses JSON,
                    evaluation_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (benchmark_result_id) REFERENCES benchmark_results(id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci
            """)
            # Get responses that haven't been evaluated
            query = """
                SELECT br.*, p.prompt_text
                FROM benchmark_results br
                LEFT JOIN evaluation_results er ON br.id = er.benchmark_result_id
                LEFT JOIN prompts p ON br.prompt_id = p.id
                WHERE br.response_text IS NOT NULL
                AND er.benchmark_result_id IS NULL
                ORDER BY br.id
            """
            cursor.execute(query)
            results = cursor.fetchall()
            cursor.close()
            print(f"Found {len(results)} responses to evaluate")
            return results
        except Error as e:
            print(f"Error fetching data: {e}")
            return []
    
    def create_evaluation_prompt(self, original_prompt, model_response):
        """Create the evaluation prompt for Gemini"""
        return f"""You are an expert evaluator assessing the quality of responses from different language models. You will evaluate responses across multiple dimensions and provide detailed, objective feedback.
Task: Evaluate the following model response to the given prompt.

<original_prompt>{original_prompt}</original_prompt>
<model_response>{model_response}</model_response>

Evaluation Criteria
Please rate the response on a scale of 1-5 for each dimension:
1. Accuracy (1-5)

5: Completely accurate, no factual errors
4: Mostly accurate with minor inaccuracies that don't affect main points
3: Generally accurate but contains some notable errors
2: Several significant errors that undermine reliability
1: Mostly inaccurate or fundamentally wrong

2. Completeness (1-5)

5: Fully addresses all aspects of the prompt comprehensively
4: Addresses most important aspects with minor gaps
3: Covers main points but misses some important elements
2: Incomplete response with significant gaps
1: Severely incomplete or fails to address the prompt

3. Clarity and Communication (1-5)

5: Exceptionally clear, well-structured, easy to understand
4: Clear and well-organized with good flow
3: Generally clear but may have some confusing sections
2: Somewhat unclear or poorly organized
1: Very unclear, confusing, or poorly structured

4. Domain Expertise (1-5)

5: Demonstrates deep understanding and expert-level knowledge
4: Shows solid understanding with appropriate technical depth
3: Basic understanding with some technical accuracy
2: Limited understanding with notable knowledge gaps
1: Poor understanding or significant misconceptions

5. Helpfulness and Practical Value (1-5)

5: Extremely useful, actionable, and valuable to the user
4: Very helpful with practical insights
3: Moderately helpful, provides some value
2: Somewhat helpful but limited practical value
1: Not helpful or potentially misleading

Output Format
Provide your evaluation in the following JSON format:

{{
  "accuracy": {{
    "score": [1-5],
    "justification": "Brief explanation of score"
  }},
  "completeness": {{
    "score": [1-5],
    "justification": "Brief explanation of score"
  }},
  "clarity": {{
    "score": [1-5],
    "justification": "Brief explanation of score"
  }},
  "domain_expertise": {{
    "score": [1-5],
    "justification": "Brief explanation of score"
  }},
  "helpfulness": {{
    "score": [1-5],
    "justification": "Brief explanation of score"
  }},
  "overall_score": [calculated average],
  "overall_assessment": "2-3 sentence summary of the response quality",
  "key_strengths": ["strength 1", "strength 2"],
  "key_weaknesses": ["weakness 1", "weakness 2"]
}}"""
    
    def evaluate_response(self, original_prompt, model_response):
        """Evaluate a single response using Gemini API"""
        try:
            evaluation_prompt = self.create_evaluation_prompt(original_prompt, model_response)
            contents = [
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=evaluation_prompt)],
                )
            ]
            generate_content_config = types.GenerateContentConfig(
                response_mime_type="text/plain",
            )
            # Collect the streaming response
            response_text = ""
            for chunk in self.gemini_client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=generate_content_config,
            ):
                response_text += chunk.text
            # Parse JSON response
            try:
                # Clean the response text - remove markdown code blocks if present
                cleaned_text = response_text.strip()
                if cleaned_text.startswith('```json'):
                    cleaned_text = cleaned_text[7:]  # Remove ```json
                if cleaned_text.endswith('```'):
                    cleaned_text = cleaned_text[:-3]  # Remove closing ```
                cleaned_text = cleaned_text.strip()
                evaluation_data = json.loads(cleaned_text)
                return evaluation_data
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON response: {e}")
                print(f"Original response text: {response_text}")
                print(f"Cleaned response text: {cleaned_text}")
                return None
        except Exception as e:
            print(f"Error evaluating response: {e}")
            return None
    
    def save_evaluation(self, connection, benchmark_result_id, evaluation_data):
        """Save evaluation results to database"""
        try:
            cursor = connection.cursor()
            insert_query = """
                INSERT INTO evaluation_results (
                    benchmark_result_id, accuracy_score, accuracy_justification,
                    completeness_score, completeness_justification,
                    clarity_score, clarity_justification,
                    domain_expertise_score, domain_expertise_justification,
                    helpfulness_score, helpfulness_justification,
                    overall_score, overall_assessment,
                    key_strengths, key_weaknesses
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                benchmark_result_id,
                evaluation_data['accuracy']['score'],
                evaluation_data['accuracy']['justification'],
                evaluation_data['completeness']['score'],
                evaluation_data['completeness']['justification'],
                evaluation_data['clarity']['score'],
                evaluation_data['clarity']['justification'],
                evaluation_data['domain_expertise']['score'],
                evaluation_data['domain_expertise']['justification'],
                evaluation_data['helpfulness']['score'],
                evaluation_data['helpfulness']['justification'],
                evaluation_data['overall_score'],
                evaluation_data['overall_assessment'],
                json.dumps(evaluation_data['key_strengths']),
                json.dumps(evaluation_data['key_weaknesses'])
            )
            cursor.execute(insert_query, values)
            connection.commit()
            cursor.close()
            return True
        except Error as e:
            print(f"Error saving evaluation: {e}")
            return False
    
    def run_evaluation(self):
        """Main evaluation loop"""
        connection = self.connect_to_database()
        if not connection:
            return
        try:
            responses = self.get_unevaluated_responses(connection)
            if not responses:
                print("No responses found for evaluation.")
                return
            total_responses = len(responses)
            successful_evaluations = 0
            failed_evaluations = 0
            for i, response in enumerate(responses, 1):
                print(f"\nEvaluating response {i}/{total_responses} - ID: {response['id']}, Model: {response['model']}")
                # Get the original prompt - adjust this based on your prompts table structure
                original_prompt = response.get('prompt_text', 'Original prompt not available')
                model_response = response['response_text']
                # Evaluate the response
                evaluation_data = self.evaluate_response(original_prompt, model_response)
                if evaluation_data:
                    # Save evaluation to database
                    if self.save_evaluation(connection, response['id'], evaluation_data):
                        successful_evaluations += 1
                        print(f"✓ Successfully evaluated and saved (Overall Score: {evaluation_data['overall_score']})")
                    else:
                        failed_evaluations += 1
                        print("✗ Failed to save evaluation")
                else:
                    failed_evaluations += 1
                    print("✗ Failed to evaluate response")
                # Add a small delay to avoid rate limiting
                time.sleep(1)
            print(f"\n=== Evaluation Summary ===")
            print(f"Total responses: {total_responses}")
            print(f"Successful evaluations: {successful_evaluations}")
            print(f"Failed evaluations: {failed_evaluations}")
        finally:
            connection.close()
            print("Database connection closed.")

def main():
    # Load environment variables from .env file
    load_dotenv()
    
    # Get Gemini API key from environment
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        print("Error: GEMINI_API_KEY not found in environment variables.")
        print("Please create a .env file with GEMINI_API_KEY=your_api_key_here")
        sys.exit(1)
    
    parser = argparse.ArgumentParser(description='Evaluate LLM responses using Gemini API')
    parser.add_argument('--host', required=True, help='MySQL host')
    parser.add_argument('--port', type=int, default=3306, help='MySQL port')
    parser.add_argument('--user', required=True, help='MySQL username')
    parser.add_argument('--password', required=True, help='MySQL password')
    parser.add_argument('--database', required=True, help='MySQL database name')
    
    args = parser.parse_args()
    
    # Database configuration
    db_config = {
        'host': args.host,
        'port': args.port,
        'user': args.user,
        'password': args.password,
        'database': args.database,
        'charset': 'utf8mb4',
        'use_unicode': True,
        'autocommit': True
    }
    
    # Initialize and run evaluator
    evaluator = LLMEvaluator(db_config, gemini_api_key)
    evaluator.run_evaluation()

if __name__ == "__main__":
    main()