# LLM Response Evaluator using Gemini API
# To run this code you need to install the following dependencies:
# pip install google-genai mysql-connector-python python-dotenv

import argparse
import json
import re
import mysql.connector
from mysql.connector import Error
from google import genai
from google.genai import types
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import sys
import os
from dotenv import load_dotenv
from db_env import add_db_args

MAX_RESPONSE_CHARS = 30000
EVAL_DIMENSIONS = ('accuracy', 'completeness', 'clarity', 'domain_expertise', 'helpfulness')
MAX_EVAL_ATTEMPTS = 3

def _json_candidates(text):
    """Yield possible JSON object strings found in an evaluator reply, most likely first."""
    text = text.strip()
    for m in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE):
        yield m.group(1)
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end > start:
        yield text[start:end + 1]

def _repair_json(candidate):
    """Fix common LLM JSON slips: invalid backslash escapes (e.g. a regex quoted in a justification) and trailing commas."""
    # Valid escapes are kept whole (so a '\\' pair is never split); any other lone backslash is doubled
    fixed = re.sub(r'\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4})|\\', lambda m: m.group(0) if len(m.group(0)) > 1 else '\\\\', candidate)
    return re.sub(r',(\s*[}\]])', r'\1', fixed)

def _escape_inner_quotes(candidate):
    """Escape double quotes inside string values (e.g. quoted code in a justification).

    A quote closes a string only when the next non-blank character is one of , } ] : -
    any other quote met inside a string is treated as part of the text.
    """
    out = []
    in_string = False
    i = 0
    while i < len(candidate):
        ch = candidate[i]
        if in_string and ch == '\\' and i + 1 < len(candidate):
            out.append(candidate[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_string:
                in_string = True
            else:
                j = i + 1
                while j < len(candidate) and candidate[j] in ' \t\r\n':
                    j += 1
                if j >= len(candidate) or candidate[j] in ',}]:':
                    in_string = False
                else:
                    out.append('\\')
        out.append(ch)
        i += 1
    return ''.join(out)

def parse_evaluation_json(text):
    """Parse the evaluator reply into a dict, tolerating prose, code fences and minor JSON errors."""
    last_error = None
    for candidate in _json_candidates(text):
        for variant in (candidate, _repair_json(candidate), _repair_json(_escape_inner_quotes(candidate))):
            try:
                data = json.loads(variant, strict=False)
            except json.JSONDecodeError as e:
                last_error = e
                continue
            if isinstance(data, dict):
                return data
    raise ValueError(f"no valid JSON object found ({last_error})")

def validate_evaluation(data):
    """Check and normalise the evaluation so that saving it cannot fail halfway."""
    scores = []
    for dim in EVAL_DIMENSIONS:
        item = data.get(dim)
        if not isinstance(item, dict):
            raise ValueError(f"missing dimension '{dim}'")
        try:
            score = int(round(float(item.get('score'))))
        except (TypeError, ValueError):
            raise ValueError(f"'{dim}' has no numeric score")
        if not 1 <= score <= 5:
            raise ValueError(f"'{dim}' score {score} outside 1-5")
        item['score'] = score
        item['justification'] = str(item.get('justification', ''))
        scores.append(score)
    try:
        overall = float(data.get('overall_score'))
    except (TypeError, ValueError):
        overall = None
    if overall is None or not 1 <= overall <= 5:
        overall = round(sum(scores) / len(scores), 2)
    data['overall_score'] = overall
    data['overall_assessment'] = str(data.get('overall_assessment', ''))
    for key in ('key_strengths', 'key_weaknesses'):
        value = data.get(key)
        data[key] = value if isinstance(value, list) else ([] if value is None else [str(value)])
    return data

class LLMEvaluator:
    def __init__(self, db_config, config, model=None, workers=1):
        self.db_config = db_config
        self.workers = max(1, workers)
        self.model_filter = model
        self.config = config
        self.eval_type = config.get('EVALUATOR_TYPE', 'gemini').lower()
        self.model = config.get('EVAL_MODEL', 'gemini-1.5-flash' if self.eval_type == 'gemini' else 'gpt-4o-mini')
        
        if self.eval_type == 'gemini':
            gemini_api_key = config.get('GEMINI_API_KEY')
            if not gemini_api_key:
                raise ValueError("GEMINI_API_KEY not found in environment variables.")
            self.gemini_client = genai.Client(api_key=gemini_api_key)
        else:
            self.base_url = config.get('EVAL_BASE_URL', 'https://api.openai.com/v1')
            self.api_key = config.get('EVAL_API_KEY')
            if not self.api_key:
                raise ValueError("EVAL_API_KEY not found in environment variables.")
            print(f"Using OpenAI-compatible evaluator: {self.model} at {self.base_url}")

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
            # Migrate: track which evaluator produced each score (existing rows come from Gemini)
            cursor.execute("""
                SELECT COUNT(*) AS n FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'evaluation_results' AND COLUMN_NAME = 'evaluator'
            """)
            if cursor.fetchone()['n'] == 0:
                cursor.execute("ALTER TABLE evaluation_results ADD COLUMN evaluator VARCHAR(100) NOT NULL DEFAULT '', ADD INDEX idx_evaluator (evaluator)")
                cursor.execute("UPDATE evaluation_results SET evaluator = 'gemini' WHERE evaluator = ''")
            # Get responses that haven't been evaluated by the current evaluator
            query = """
                SELECT br.*, p.prompt_text, p.goldenAnswer
                FROM benchmark_results br
                LEFT JOIN evaluation_results er ON br.id = er.benchmark_result_id AND er.evaluator = %s
                LEFT JOIN prompts p ON br.prompt_id = p.id
                WHERE br.response_text IS NOT NULL
                AND er.benchmark_result_id IS NULL
            """
            params = [self.model]
            if self.model_filter:
                query += " AND br.model = %s"
                params.append(self.model_filter)
            query += " ORDER BY br.id"
            cursor.execute(query, params)
            results = cursor.fetchall()
            cursor.close()
            print(f"Found {len(results)} responses to evaluate")
            return results
        except Error as e:
            print(f"Error fetching data: {e}")
            return []
    
    def create_evaluation_prompt(self, original_prompt, model_response, golden_answer=None):
        """Create the evaluation prompt for the LLM"""
        
        golden_answer_section = ""
        comparison_instruction = ""
        
        if golden_answer:
            golden_answer_section = f"\n<golden_answer>{golden_answer}</golden_answer>"
            comparison_instruction = " Compare the model's response with the provided golden answer for accuracy and completeness."

        return f"""You are an expert evaluator assessing the quality of responses from different language models. You will evaluate responses across multiple dimensions and provide detailed, objective feedback.{comparison_instruction}
Task: Evaluate the following model response to the given prompt.

<original_prompt>{original_prompt}</original_prompt>{golden_answer_section}
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
    
    def request_evaluation(self, original_prompt, model_response, golden_answer=None):
        """Call the configured LLM API once and return the raw reply text (None on API failure)"""
        try:
            if len(model_response) > MAX_RESPONSE_CHARS:
                model_response = model_response[:MAX_RESPONSE_CHARS] + f"\n\n[... response truncated, original length {len(model_response)} characters ...]"
            evaluation_prompt = self.create_evaluation_prompt(original_prompt, model_response, golden_answer)
            
            if self.eval_type == 'gemini':
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
            else:
                # OpenAI-compatible API using requests
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": self.model,
                    "messages": [{"role": "user", "content": evaluation_prompt}]
                }
                # Newer Claude models reject the temperature parameter
                if not self.model.startswith("anthropic/"):
                    data["temperature"] = 0.1
                # Optional JSON response format for supported models
                if "gpt-4" in self.model or "gpt-3.5-turbo-1106" in self.model:
                    data["response_format"] = {"type": "json_object"}
                    
                # Retry: the proxy intermittently fails (e.g. one deployment with a bad key)
                for attempt in range(4):
                    response = requests.post(
                        f"{self.base_url.rstrip('/')}/chat/completions",
                        headers=headers,
                        json=data,
                        timeout=300
                    )
                    if response.status_code == 200:
                        break
                    time.sleep(2 * (attempt + 1))
                
                if response.status_code != 200:
                    print(f"Error calling OpenAI-compatible API: {response.status_code} - {response.text}")
                    return None
                    
                response_json = response.json()
                response_text = response_json['choices'][0]['message']['content']

            return response_text
        except Exception as e:
            print(f"Error evaluating response: {e}")
            return None

    def evaluate_response(self, original_prompt, model_response, golden_answer=None):
        """Evaluate a single response; re-ask the evaluator when its reply can't be parsed or validated"""
        for attempt in range(1, MAX_EVAL_ATTEMPTS + 1):
            response_text = self.request_evaluation(original_prompt, model_response, golden_answer)
            if response_text is None:
                return None
            try:
                return validate_evaluation(parse_evaluation_json(response_text))
            except ValueError as e:
                print(f"Unusable evaluator reply (attempt {attempt}/{MAX_EVAL_ATTEMPTS}): {e}")
                print(f"Reply start: {response_text[:300]!r}")
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
                    key_strengths, key_weaknesses, evaluator
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                json.dumps(evaluation_data['key_weaknesses']),
                self.model
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

            def evaluate_one(response):
                evaluation_data = self.evaluate_response(
                    response.get('prompt_text', 'Original prompt not available'),
                    response['response_text'],
                    response.get('goldenAnswer'))
                if self.eval_type == 'gemini':
                    time.sleep(4)  # RPM=15 for free tier API key, so 4 second sleep
                return evaluation_data

            with ThreadPoolExecutor(max_workers=self.workers) as executor:
                futures = {executor.submit(evaluate_one, r): r for r in responses}
                for done, future in enumerate(as_completed(futures), 1):
                    response = futures[future]
                    label = f"[{done}/{total_responses}] ID: {response['id']}, Model: {response['model']}"
                    try:
                        evaluation_data = future.result()
                    except Exception as e:
                        print(f"✗ {label} - unexpected error: {e}", flush=True)
                        failed_evaluations += 1
                        continue
                    if not evaluation_data:
                        failed_evaluations += 1
                        print(f"✗ {label} - failed to evaluate", flush=True)
                    elif self.save_evaluation(connection, response['id'], evaluation_data):
                        successful_evaluations += 1
                        print(f"✓ {label} - saved (Overall Score: {evaluation_data['overall_score']})", flush=True)
                    else:
                        failed_evaluations += 1
                        print(f"✗ {label} - failed to save", flush=True)
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
    
    # Get all environment variables for configuration
    config = {
        'EVALUATOR_TYPE': os.getenv('EVALUATOR_TYPE', 'gemini'),
        'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
        'EVAL_BASE_URL': os.getenv('EVAL_BASE_URL'),
        'EVAL_MODEL': os.getenv('EVAL_MODEL'),
        'EVAL_API_KEY': os.getenv('EVAL_API_KEY')
    }
    
    parser = argparse.ArgumentParser(description='Evaluate LLM responses using Gemini or OpenAI-compatible API')
    add_db_args(parser)
    parser.add_argument('--workers', type=int, default=1, help='Number of parallel evaluation requests (default: 1)')
    parser.add_argument('--model', help='Evaluate only responses of this model (default: all models)')
    
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
    try:
        evaluator = LLMEvaluator(db_config, config, args.model, args.workers)
        evaluator.run_evaluation()
    except ValueError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()