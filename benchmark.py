import mysql.connector
import requests
import json
import time
from datetime import datetime
import argparse
import os
from typing import Dict, List, Any, Tuple
from db_env import add_db_args

# A model stuck in a loop is a failed answer: generation stops at the token limit or as soon as
# the last LOOP_WINDOW characters repeat exactly with a period of LOOP_MIN_PERIOD..LOOP_MAX_PERIOD.
DEFAULT_MAX_TOKENS = 32768
LOOP_WINDOW = 3000
LOOP_MIN_PERIOD = 10
LOOP_MAX_PERIOD = 1000
LOOP_CHECK_EVERY = 200  # stream chunks (about one token each)


def find_loop_period(text: str) -> int:
    """Return the period if the tail of text is one block repeated over LOOP_WINDOW chars, else 0."""
    if len(text) < LOOP_WINDOW + LOOP_MIN_PERIOD:
        return 0
    tail = text[-LOOP_WINDOW:]
    for p in range(LOOP_MIN_PERIOD, min(LOOP_MAX_PERIOD, len(text) - LOOP_WINDOW) + 1):
        if text[-LOOP_WINDOW - p:-p] == tail:
            return p
    return 0


class LLMBenchmark:
    def __init__(self, db_config: Dict[str, str], ollama_base_url: str = "http://localhost:11434",
                 max_tokens: int = DEFAULT_MAX_TOKENS):
        """
        Initialize the LLM benchmarking framework.

        Args:
            db_config: Dictionary with MySQL connection parameters
            ollama_base_url: Base URL for Ollama API
            max_tokens: num_predict limit; an answer that reaches it is saved as a failure
        """
        self.db_config = db_config
        self.ollama_base_url = ollama_base_url
        self.max_tokens = max_tokens
        self.conn = None
        self.cursor = None
        
    def connect_db(self) -> None:
        """Establish connection to MySQL database."""
        try:
            self.conn = mysql.connector.connect(**self.db_config)
            self.cursor = self.conn.cursor(dictionary=True)
            print("Successfully connected to MySQL database")
        except mysql.connector.Error as err:
            print(f"Error connecting to MySQL database: {err}")
            raise
            
    def close_db(self) -> None:
        """Close database connection."""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
            print("Database connection closed")
            
    def get_prompts(self, prompt_id: int = None, limit: int = None) -> List[Dict[str, Any]]:
        """
        Retrieve prompts from the database.
        
        Args:
            prompt_id: Optional specific prompt ID to retrieve
            limit: Optional limit on number of prompts to retrieve
            
        Returns:
            List of prompt dictionaries
        """
        query = "SELECT id, prompt_text, category, tags FROM prompts"
        params = []
        
        if prompt_id is not None:
            query += " WHERE id = %s"
            params.append(prompt_id)
            
        if limit:
            query += f" LIMIT {limit}"
            
        self.cursor.execute(query, params)
        prompts = self.cursor.fetchall()
        print(f"Retrieved {len(prompts)} prompts from database")
        return prompts
    
    def get_model_capabilities(self, model: str) -> List[str]:
        """
        Get the capabilities Ollama reports for a model (e.g. completion, embedding, decision).

        Returns:
            List of capability names, empty if the model doesn't report any or the lookup fails
        """
        try:
            response = requests.post(f"{self.ollama_base_url}/api/show", json={'model': model}, timeout=30)
            if response.status_code == 200:
                return response.json().get('capabilities') or []
            print(f"Warning: could not read capabilities of {model}: HTTP {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"Warning: could not read capabilities of {model}: {e}")
        return []

    def get_all_available_models(self) -> List[str]:
        """
        Get all available models from Ollama, filtering out blacklisted models
        and models without a completion or chat capability (embedding, decision, ...).

        Returns:
            List of model names that support completion interface
        """
        # Define blacklisted model patterns/names
        blacklisted_patterns = [
            'nomic-embed-text',
            'embed',
            'embedding',
            'bge-',
            'e5-',
            'sentence-transformers',
            'all-minilm',
            'paraphrase-',
            'distilbert',
            'instructor-',
            'gte-',
            'multilingual-e5',
            'ocr',  # OCR models (deepseek-ocr, GLM-OCR, ...)
            'basal',  # decision models, although Ollama reports them as completion
            'llama3.3:latest',
            'qwen2.5-coder:14b'
        ]
        
        try:
            response = requests.get(f"{self.ollama_base_url}/api/tags")
            if response.status_code == 200:
                all_models = [model['name'] for model in response.json()['models']]
                
                # Filter out blacklisted models
                filtered_models = []
                for model in all_models:
                    model_lower = model.lower()
                    is_blacklisted = any(pattern.lower() in model_lower for pattern in blacklisted_patterns)
                    
                    if is_blacklisted:
                        print(f"Filtered out model: {model} (no completion interface)")
                        continue

                    capabilities = self.get_model_capabilities(model)
                    # Models that don't report capabilities (older Ollama builds) are kept
                    if capabilities and not {'completion', 'chat'} & set(capabilities):
                        print(f"Filtered out model: {model} (capabilities: {', '.join(capabilities)}; no completion or chat)")
                        continue

                    filtered_models.append(model)
                
                return filtered_models
            else:
                print(f"Error retrieving models: {response.status_code}")
                return []
        
        except requests.exceptions.RequestException as e:
            print(f"Network error retrieving models: {e}")
            return []
    
    def validate_and_filter_models(self, requested_models: List[str]) -> List[str]:
        """
        Validate requested models against available models and apply blacklist.
        
        Args:
            requested_models: List of model names requested by user
            
        Returns:
            List of valid, available, non-blacklisted models
        """
        available_models = self.get_all_available_models()
        
        if not available_models:
            print("No models available from Ollama")
            return []
        
        valid_models = []
        for model in requested_models:
            if model in available_models:
                valid_models.append(model)
            else:
                print(f"Warning: Model '{model}' not found or blacklisted, skipping")
        
        return valid_models
            
    def check_result_exists(self, prompt_id: int, model: str) -> bool:
        """
        Check if a result already exists for a specific prompt and model.
        
        Args:
            prompt_id: ID of the prompt
            model: Name of the model
            
        Returns:
            True if result exists, False otherwise
        """
        query = """
            SELECT COUNT(*) as count
            FROM benchmark_results
            WHERE prompt_id = %s AND model = %s
        """
        self.cursor.execute(query, (prompt_id, model))
        result = self.cursor.fetchone()
        return result['count'] > 0
            
    def run_prompt(self, model: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a prompt to a model and get the response with metrics.
        
        Args:
            model: Name of the LLM model to use
            prompt: Prompt dictionary with 'id' and 'prompt_text'
            
        Returns:
            Dictionary with response and metrics
        """
        print(f"Running prompt {prompt['id']} on model {model}")
        
        request_data = {
            "model": model,
            "prompt": prompt['prompt_text'],
            "stream": True,
            "options": {"num_predict": self.max_tokens}
        }

        start_time = time.time()
        try:
            response = requests.post(
                f"{self.ollama_base_url}/api/generate",
                json=request_data,
                stream=True
            )
        except requests.exceptions.RequestException as e:
            print(f"Error calling Ollama API: {e}")
            return {
                "prompt_id": prompt['id'],
                "model": model,
                "success": False,
                "transient": True,
                "error": f"Request failed: {e}",
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        if response.status_code != 200:
            print(f"Error calling Ollama API: {response.status_code}")
            response.close()
            return {
                "prompt_id": prompt['id'],
                "model": model,
                "success": False,
                "transient": response.status_code >= 500,
                "error": f"API Error: {response.status_code}",
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        text, thinking = [], []
        final = {}
        chunks = 0
        loop_error = None
        first_token_time = None
        try:
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get('error'):
                    raise requests.exceptions.RequestException(chunk['error'])
                if chunk.get('response'):
                    text.append(chunk['response'])
                if chunk.get('thinking'):
                    thinking.append(chunk['thinking'])
                if chunk.get('done'):
                    final = chunk
                    break
                chunks += 1
                if first_token_time is None:
                    first_token_time = time.time()
                if chunks % LOOP_CHECK_EVERY == 0:
                    for part, label in ((text, 'answer'), (thinking, 'thinking')):
                        period = find_loop_period(''.join(part))
                        if period:
                            loop_error = f"Runaway generation: {label} repeats every {period} chars after {chunks} tokens"
                            break
                    if loop_error:
                        break  # closing the connection makes Ollama stop generating
        except (requests.exceptions.RequestException, ValueError) as e:
            response.close()
            print(f"Error reading Ollama stream: {e}")
            return {
                "prompt_id": prompt['id'],
                "model": model,
                "success": False,
                "transient": True,
                "error": f"Stream failed: {e}",
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        finally:
            response.close()
        end_time = time.time()

        response_text = ''.join(text)
        if loop_error is None and final.get('done_reason') == 'length':
            loop_error = f"Runaway generation: hit the {self.max_tokens}-token limit"

        if loop_error:
            # success = the model gave a usable answer; a loop never is (human thumbs live in human_rating)
            success, error = False, loop_error
            print(f"   - {loop_error}")
        elif not response_text.strip():
            success, error = False, 'Empty response'
        else:
            success, error = True, None

        if final:
            eval_count = final.get('eval_count', 0)
            eval_duration = final.get('eval_duration', 0)
        else:
            # stopped early: no final stats from Ollama, estimate from the stream
            eval_count = chunks
            eval_duration = int((end_time - (first_token_time or start_time)) * 1e9)

        result = {
            "prompt_id": prompt['id'],
            "model": model,
            "success": success,
            "error": error,
            "response_text": response_text,
            "total_duration": end_time - start_time,
            "eval_count": eval_count,
            "eval_duration": eval_duration,
            "load_duration": final.get('load_duration', 0),
            "prompt_eval_count": final.get('prompt_eval_count', 0),
            "prompt_eval_duration": final.get('prompt_eval_duration', 0),
            "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        return result
    
    def save_result(self, result: Dict[str, Any]) -> int:
        """
        Save benchmark result to database.
        
        Args:
            result: Dictionary with response and metrics
            
        Returns:
            ID of inserted record
        """
        if 'response_text' not in result:
            # request error: no answer and no metrics
            query = """
                INSERT INTO benchmark_results 
                (prompt_id, model, success, error, timestamp)
                VALUES (%s, %s, %s, %s, %s)
            """
            values = (
                result['prompt_id'],
                result['model'],
                result['success'],
                result.get('error', ''),
                result['timestamp']
            )
        else:
            query = """
                INSERT INTO benchmark_results 
                (prompt_id, model, success, error, response_text, total_duration,
                eval_count, eval_duration, load_duration,
                prompt_eval_count, prompt_eval_duration, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                result['prompt_id'],
                result['model'],
                result['success'],
                result.get('error'),
                result['response_text'],
                result['total_duration'],
                result['eval_count'],
                result['eval_duration'],
                result['load_duration'],
                result['prompt_eval_count'],
                result['prompt_eval_duration'],
                result['timestamp']
            )
            
        self.cursor.execute(query, values)
        self.conn.commit()
        
        return self.cursor.lastrowid
        
    def run_benchmark(self, models: List[str] = None, prompt_limit: int = None, force_regenerate: bool = False, specific_prompt_id: int = None) -> None:
        """
        Run benchmark across specified models and prompts.
        
        Args:
            models: List of models to benchmark, defaults to all available
            prompt_limit: Optional limit on number of prompts to use
            force_regenerate: Whether to regenerate answers even if they exist
            specific_prompt_id: Optional specific prompt ID to benchmark
        """
        try:
            self.connect_db()
            
            if not models:
                models = self.get_all_available_models()
            else:
                models = self.validate_and_filter_models(models)
                
            if not models:
                print("No valid models available for benchmarking")
                return
            
            print(f"Models to benchmark: {', '.join(models)}")
               
            prompts = self.get_prompts(prompt_id=specific_prompt_id, limit=prompt_limit)
            if not prompts:
                print("No prompts found in database")
                return
                
            print(f"Starting benchmark with {len(models)} models and {len(prompts)} prompts")
            
            for model in models:
                print(f"\nBenchmarking model: {model}")
                for prompt in prompts:
                    # Check if result exists and if we should skip
                    if not force_regenerate and self.check_result_exists(prompt['id'], model):
                        print(f"  - Prompt {prompt['id']} already has results for model {model}, skipping")
                        continue
                    
                    result = self.run_prompt(model, prompt)
                    if result.get('transient'):
                        # Server-side/network error: don't store it, so a rerun retries this prompt
                        print(f"   - Prompt {prompt['id']} not saved (transient error: {result.get('error')}), will be retried on the next run")
                        time.sleep(30)
                        continue
                    result_id = self.save_result(result)
                    
                    if result.get('success'):
                        duration = result.get('total_duration', 0)
                        eval_count = result.get('eval_count', 0)
                        eval_duration_s = result.get('eval_duration', 0) / 1e9
                        eval_ts = (eval_count / eval_duration_s) if eval_duration_s > 0 else 0
                        
                        prompt_eval_count = result.get('prompt_eval_count', 0)
                        prompt_eval_duration_s = result.get('prompt_eval_duration', 0) / 1e9
                        prompt_eval_ts = (prompt_eval_count / prompt_eval_duration_s) if prompt_eval_duration_s > 0 else 0
                        
                        print(f"   - Prompt {prompt['id']} completed, result ID: {result_id} Total: {duration:.3f}s Eval Count: {eval_count} ({eval_ts:.2f} t/s) Eval Duration: {eval_duration_s:.3f}s Prompt Eval Count: {prompt_eval_count} ({prompt_eval_ts:.0f} t/s) Prompt Eval Duration: {prompt_eval_duration_s:.3f}s")
                    else:
                        print(f"   - Prompt {prompt['id']} failed, result ID: {result_id} Error: {result.get('error', 'Unknown Error')}")
                    
            print("\nBenchmark completed successfully")
            
        except Exception as e:
            print(f"Error running benchmark: {str(e)}")
        finally:
            self.close_db()
            
    def generate_report(self) -> Dict[str, Any]:
        """
        Generate a simple benchmark report.
        
        Returns:
            Dictionary with benchmark statistics
        """
        try:
            self.connect_db()
            
            # Get models stats
            self.cursor.execute("""
                SELECT model, 
                       COUNT(*) as total_prompts,
                       AVG(total_duration) as avg_duration,
                       AVG(eval_count) as avg_eval_count,
                       MIN(total_duration) as min_duration,
                       MAX(total_duration) as max_duration
                FROM benchmark_results
                WHERE success = 1
                GROUP BY model
            """)
            
            model_stats = self.cursor.fetchall()
            
            # Get category stats
            self.cursor.execute("""
                SELECT p.category, r.model,
                       COUNT(*) as total_prompts,
                       AVG(total_duration) as avg_duration
                FROM benchmark_results r
                JOIN prompts p ON r.prompt_id = p.id
                WHERE r.success = 1
                GROUP BY p.category, r.model
            """)
            
            category_stats = self.cursor.fetchall()
            
            report = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "model_stats": model_stats,
                "category_stats": category_stats
            }
            
            return report
            
        except Exception as e:
            print(f"Error generating report: {str(e)}")
            return {"error": str(e)}
        finally:
            self.close_db()

# Example usage
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LLM Benchmark Framework')
    add_db_args(parser)
    parser.add_argument('--ollama', default='http://localhost:11434', help='Ollama API base URL')
    parser.add_argument('--models', help='Comma-separated list of models to benchmark (e.g., llama2,mistral,phi)')
    parser.add_argument('--all-models', action='store_true', default=True, help='Benchmark all available models (default)')
    parser.add_argument('--limit', type=int, help='Limit number of prompts')
    parser.add_argument('--report', action='store_true', help='Generate report only')
    parser.add_argument('--prompt-id', type=int, help='Run benchmark for a specific prompt ID')
    parser.add_argument('--force', action='store_true', help='Force regeneration of results even if they exist')
    parser.add_argument('--max-tokens', type=int, default=DEFAULT_MAX_TOKENS,
                        help=f'num_predict limit; reaching it marks the answer as failed (default {DEFAULT_MAX_TOKENS})')

    args = parser.parse_args()
    
    db_config = {
        'host': args.host,
        'port': args.port,
        'user': args.user,
        'password': args.password,
        'database': args.database,
        'charset': 'utf8mb4'
    }
    
    benchmark = LLMBenchmark(db_config, args.ollama, args.max_tokens)
    
    if args.report:
        report = benchmark.generate_report()
        print(json.dumps(report, indent=2, default=str))
    else:
        # Parse models if provided
        models_to_benchmark = None
        if args.models:
            models_to_benchmark = [m.strip() for m in args.models.split(',')]
            print(f"Requested models: {', '.join(models_to_benchmark)}")
        elif args.all_models:
            print("Using all available models (default)")
        
        # If a specific prompt ID is provided, force regeneration is automatically true
        force_regenerate = args.force or args.prompt_id is not None
        benchmark.run_benchmark(
            models=models_to_benchmark, 
            prompt_limit=args.limit, 
            force_regenerate=force_regenerate,
            specific_prompt_id=args.prompt_id
        )