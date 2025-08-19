import mysql.connector
import requests
import json
import time
from datetime import datetime
import argparse
import os
from typing import Dict, List, Any, Tuple

class LLMBenchmark:
    def __init__(self, db_config: Dict[str, str], ollama_base_url: str = "http://localhost:11434"):
        """
        Initialize the LLM benchmarking framework.
        
        Args:
            db_config: Dictionary with MySQL connection parameters
            ollama_base_url: Base URL for Ollama API
        """
        self.db_config = db_config
        self.ollama_base_url = ollama_base_url
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
    
    def get_models(self) -> List[str]:
        """
        Get available models from Ollama, filtering out blacklisted models.
        
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
            'multilingual-e5'
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
                    
                    if not is_blacklisted:
                        filtered_models.append(model)
                    else:
                        print(f"Filtered out model: {model} (no completion interface)")
                
                print(f"Available completion models: {', '.join(filtered_models)}")
                return filtered_models
            else:
                print(f"Error retrieving models: {response.status_code}")
                return []
        
        except requests.exceptions.RequestException as e:
            print(f"Network error retrieving models: {e}")
            return []
            
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
            "stream": False
        }
        
        start_time = time.time()
        response = requests.post(
            f"{self.ollama_base_url}/api/generate", 
            json=request_data
        )
        end_time = time.time()
        
        if response.status_code != 200:
            print(f"Error calling Ollama API: {response.status_code}")
            return {
                "prompt_id": prompt['id'],
                "model": model,
                "success": False,
                "error": f"API Error: {response.status_code}"
            }
            
        response_data = response.json()
        
        result = {
            "prompt_id": prompt['id'],
            "model": model,
            "success": True,
            "response_text": response_data.get('response', ''),
            "total_duration": end_time - start_time,
            "eval_count": response_data.get('eval_count', 0),
            "eval_duration": response_data.get('eval_duration', 0),
            "load_duration": response_data.get('load_duration', 0),
            "prompt_eval_count": response_data.get('prompt_eval_count', 0),
            "prompt_eval_duration": response_data.get('prompt_eval_duration', 0),
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
        if not result['success']:
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
                (prompt_id, model, success, response_text, total_duration, 
                eval_count, eval_duration, load_duration, 
                prompt_eval_count, prompt_eval_duration, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            values = (
                result['prompt_id'],
                result['model'],
                result['success'],
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
        Run benchmark across all models and prompts.
        
        Args:
            models: List of models to benchmark, defaults to all available
            prompt_limit: Optional limit on number of prompts to use
            force_regenerate: Whether to regenerate answers even if they exist
            specific_prompt_id: Optional specific prompt ID to benchmark
        """
        try:
            self.connect_db()
            
            if not models:
                models = self.get_models()
                
            if not models:
                print("No models available for benchmarking")
                return
               
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
                    result_id = self.save_result(result)
                    print(f"  - Prompt {prompt['id']} completed, result ID: {result_id}")
                    
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
    parser.add_argument('--host', default='localhost', help='MySQL host')
    parser.add_argument('--port', type=int, default=3306, help='MySQL port')
    parser.add_argument('--user', required=True, help='MySQL username')
    parser.add_argument('--password', required=True, help='MySQL password')
    parser.add_argument('--database', required=True, help='MySQL database name')
    parser.add_argument('--ollama', default='http://localhost:11434', help='Ollama API base URL')
    parser.add_argument('--models', nargs='+', help='Models to benchmark')
    parser.add_argument('--limit', type=int, help='Limit number of prompts')
    parser.add_argument('--report', action='store_true', help='Generate report only')
    parser.add_argument('--prompt-id', type=int, help='Run benchmark for a specific prompt ID')
    parser.add_argument('--force', action='store_true', help='Force regeneration of results even if they exist')
    
    args = parser.parse_args()
    
    db_config = {
        'host': args.host,
        'port': args.port,
        'user': args.user,
        'password': args.password,
        'database': args.database,
        'charset': 'utf8mb4'
    }
    
    benchmark = LLMBenchmark(db_config, args.ollama)
    
    if args.report:
        report = benchmark.generate_report()
        print(json.dumps(report, indent=2))
    else:
        # If a specific prompt ID is provided, force regeneration is automatically true
        force_regenerate = args.force or args.prompt_id is not None
        benchmark.run_benchmark(
            models=args.models, 
            prompt_limit=args.limit, 
            force_regenerate=force_regenerate,
            specific_prompt_id=args.prompt_id
        )