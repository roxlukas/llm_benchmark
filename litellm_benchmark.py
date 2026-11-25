"""Benchmark runner for models served by a LiteLLM proxy (OpenAI-compatible /chat/completions).

Same prompts, same benchmark_results table and same failure rules as benchmark.py (loops and the
token limit count as failures); only the inference API differs. Results are stored under the
LiteLLM model name, e.g. "openai/gpt-oss-120b".

The proxy URL and key default to EVAL_BASE_URL / EVAL_API_KEY from .env (the judge's proxy);
LITELLM_BASE_URL / LITELLM_API_KEY override them.

    python litellm_benchmark.py --models deepseek/deepseek-v4.1-flash-1017,openai/gpt-oss-120b
"""
import argparse
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List

import requests

from benchmark import DEFAULT_MAX_TOKENS, LOOP_CHECK_EVERY, LLMBenchmark, find_loop_period
from db_env import add_db_args  # also loads .env

REQUEST_TIMEOUT = (15, 600)  # connect, read (seconds between stream chunks)
# On OpenRouter, Google's endpoint for openai/gpt-oss-120b ends answers mid-sentence with
# finish_reason "stop" (5 of 6 test answers, 2026-11-24); other providers answered in full.
# SiliconFlow stops deepseek/deepseek-v4.1-flash-1017 at 20% of max_tokens (6554 of 32768),
# finish_reason "length", before any answer text (2026-11-25).
DEFAULT_IGNORED_PROVIDERS = 'Google,SiliconFlow'


class LiteLLMBenchmark(LLMBenchmark):
    def __init__(self, db_config: Dict[str, str], base_url: str, api_key: str,
                 max_tokens: int = DEFAULT_MAX_TOKENS, ignore_providers: List[str] = None):
        super().__init__(db_config, max_tokens=max_tokens)
        self.ignore_providers = ignore_providers or []
        self.base_url = base_url.rstrip('/')
        self.headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}

    def get_all_available_models(self) -> List[str]:
        # The proxy also serves local, embedding and audio models: run only what was asked for
        return []

    def validate_and_filter_models(self, requested_models: List[str]) -> List[str]:
        try:
            response = requests.get(f'{self.base_url}/models', headers=self.headers, timeout=30)
            response.raise_for_status()
            available = {m['id'] for m in response.json().get('data', [])}
        except (requests.exceptions.RequestException, ValueError) as e:
            print(f'Could not list LiteLLM models: {e}')
            return []
        valid = [m for m in requested_models if m in available]
        for m in requested_models:
            if m not in available:
                print(f"Warning: Model '{m}' not served by the LiteLLM proxy, skipping")
        return valid

    def _transient(self, model, prompt, error):
        print(f'   - {error}')
        return {'prompt_id': prompt['id'], 'model': model, 'success': False, 'transient': True,
                'error': error, 'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    def run_prompt(self, model: str, prompt: Dict[str, Any]) -> Dict[str, Any]:
        print(f"Running prompt {prompt['id']} on model {model}")
        request_data = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt['prompt_text']}],
            'max_tokens': self.max_tokens,
            'stream': True,
            'stream_options': {'include_usage': True},
        }
        if self.ignore_providers:
            # OpenRouter provider routing, passed through by LiteLLM
            request_data['extra_body'] = {'provider': {'ignore': self.ignore_providers}}

        start_time = time.time()
        try:
            response = requests.post(f'{self.base_url}/chat/completions', json=request_data,
                                     headers=self.headers, stream=True, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as e:
            return self._transient(model, prompt, f'Request failed: {e}')
        if response.status_code != 200:
            body = response.text[:500]
            response.close()
            # 429 (rate limit) and 5xx are worth retrying; 4xx is a real error of this request
            if response.status_code == 429 or response.status_code >= 500:
                return self._transient(model, prompt, f'API Error: {response.status_code} {body}')
            return {'prompt_id': prompt['id'], 'model': model, 'success': False,
                    'error': f'API Error: {response.status_code} {body}',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

        text, thinking = [], []
        usage = {}
        finish_reason = None
        chunks = 0
        loop_error = None
        first_token_time = None
        try:
            for line in response.iter_lines():
                if not line or not line.startswith(b'data:'):
                    continue
                data = line[5:].strip()
                if data == b'[DONE]':
                    break
                chunk = json.loads(data)
                if chunk.get('error'):
                    raise requests.exceptions.RequestException(str(chunk['error']))
                if chunk.get('usage'):
                    usage = chunk['usage']
                for choice in chunk.get('choices') or []:
                    delta = choice.get('delta') or {}
                    if delta.get('content'):
                        text.append(delta['content'])
                    reasoning = delta.get('reasoning_content') or delta.get('reasoning')
                    if isinstance(reasoning, str) and reasoning:
                        thinking.append(reasoning)
                    if delta.get('content') or reasoning:
                        chunks += 1
                        if first_token_time is None:
                            first_token_time = time.time()
                    if choice.get('finish_reason'):
                        finish_reason = choice['finish_reason']
                if chunks and chunks % LOOP_CHECK_EVERY == 0:
                    for part, label in ((text, 'answer'), (thinking, 'thinking')):
                        period = find_loop_period(''.join(part))
                        if period:
                            loop_error = f'Runaway generation: {label} repeats every {period} chars after {chunks} chunks'
                            break
                    if loop_error:
                        break
        except (requests.exceptions.RequestException, ValueError) as e:
            return self._transient(model, prompt, f'Stream failed: {e}')
        finally:
            response.close()
        end_time = time.time()

        response_text = ''.join(text)
        if loop_error is None and finish_reason == 'length':
            loop_error = f'Runaway generation: hit the {self.max_tokens}-token limit'

        if loop_error:
            success, error = False, loop_error
            print(f'   - {loop_error}')
        elif not response_text.strip():
            success, error = False, f'Empty response (finish_reason: {finish_reason})'
        else:
            success, error = True, None

        first = first_token_time or end_time
        return {
            'prompt_id': prompt['id'],
            'model': model,
            'success': success,
            'error': error,
            'response_text': response_text,
            'total_duration': end_time - start_time,
            # completion_tokens includes reasoning tokens, like Ollama's eval_count
            'eval_count': usage.get('completion_tokens') or chunks,
            'eval_duration': int((end_time - first) * 1e9),
            'load_duration': 0,
            'prompt_eval_count': usage.get('prompt_tokens', 0),
            # time to first token: queueing + network + prompt processing at the provider
            'prompt_eval_duration': int((first - start_time) * 1e9),
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }


def main():
    parser = argparse.ArgumentParser(description='LLM benchmark for models behind a LiteLLM proxy')
    add_db_args(parser)
    parser.add_argument('--base-url', default=os.getenv('LITELLM_BASE_URL') or os.getenv('EVAL_BASE_URL'),
                        help='LiteLLM base URL ending in /v1 (LITELLM_BASE_URL, else EVAL_BASE_URL)')
    parser.add_argument('--models', required=True, help='Comma-separated LiteLLM model names')
    parser.add_argument('--limit', type=int, help='Limit number of prompts')
    parser.add_argument('--prompt-id', type=int, help='Run benchmark for a specific prompt ID')
    parser.add_argument('--force', action='store_true', help='Force regeneration of results even if they exist')
    parser.add_argument('--max-tokens', type=int, default=DEFAULT_MAX_TOKENS,
                        help=f'max_tokens; reaching it marks the answer as failed (default {DEFAULT_MAX_TOKENS})')
    parser.add_argument('--ignore-providers', default=DEFAULT_IGNORED_PROVIDERS,
                        help='Comma-separated OpenRouter providers to skip; empty string to allow all '
                             f'(default "{DEFAULT_IGNORED_PROVIDERS}")')
    args = parser.parse_args()
    if not args.base_url:
        parser.error('--base-url is required when LITELLM_BASE_URL / EVAL_BASE_URL are not in .env')

    db_config = {'host': args.host, 'port': args.port, 'user': args.user, 'password': args.password,
                 'database': args.database, 'charset': 'utf8mb4'}
    api_key = os.getenv('LITELLM_API_KEY') or os.getenv('EVAL_API_KEY')
    ignore = [p.strip() for p in args.ignore_providers.split(',') if p.strip()]
    benchmark = LiteLLMBenchmark(db_config, args.base_url, api_key, args.max_tokens, ignore)
    benchmark.run_benchmark(
        models=[m.strip() for m in args.models.split(',') if m.strip()],
        prompt_limit=args.limit,
        force_regenerate=args.force or args.prompt_id is not None,
        specific_prompt_id=args.prompt_id,
    )


if __name__ == '__main__':
    main()
