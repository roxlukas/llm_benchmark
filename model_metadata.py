#!/usr/bin/env python3
import subprocess
import json
import re
import argparse
import mysql.connector
from datetime import datetime
import sys
import locale

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Collect Ollama model metadata and store in MySQL database.')
    parser.add_argument('--host', default='localhost', help='MySQL host')
    parser.add_argument('--port', type=int, default=3306, help='MySQL port')
    parser.add_argument('--user', required=True, help='MySQL username')
    parser.add_argument('--password', required=True, help='MySQL password')
    parser.add_argument('--database', default='llm_benchmark', help='MySQL database name')
    return parser.parse_args()

def run_command(cmd):
    """Run a shell command and return the output."""
    try:
        # Use explicit encoding for Windows compatibility
        system_encoding = locale.getpreferredencoding()
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=False,  # Don't raise exception on non-zero exit
            capture_output=True, 
            text=True,
            encoding=system_encoding,
            errors='replace'  # Replace non-decodable bytes
        )
        
        if result.returncode != 0:
            print(f"Command returned non-zero exit code {result.returncode}: {cmd}")
            print(f"Error details: {result.stderr}")
            return None
            
        return result.stdout.strip() if result.stdout else None
        
    except subprocess.SubprocessError as e:
        print(f"Error executing command: {cmd}")
        print(f"Error details: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error executing command: {cmd}")
        print(f"Error details: {e}")
        return None

def get_all_models():
    """Get list of all available Ollama models."""
    output = run_command("ollama list")
    if not output:
        return []
    
    models = []
    # Skip the header line and process each model line
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 1:
            model_name = parts[0]
            models.append(model_name)
    
    return models

def parse_model_metadata(model_name):
    """Get and parse metadata for a specific model."""
    output = run_command(f"ollama show {model_name}")
    if not output:
        print(f"No output received for model: {model_name}")
        return None
    
    metadata = {
        'model_name': model_name,
        'architecture': None,
        'parameters': None,
        'context_length': None,
        'embedding_length': None,
        'quantization': None,
        'stop_tokens': [],
        'license_text': '',
        'release_date': None
    }
    
    section = None
    for line in output.splitlines():
        line = line.strip()
        
        # Detect section headers
        if line == "Model":
            section = "model"
            continue
        elif line == "Parameters":
            section = "parameters"
            continue
        elif line == "License":
            section = "license"
            continue
        
        # Skip empty lines
        if not line:
            continue
        
        # Parse model section
        if section == "model":
            # Use regex to split on multiple whitespaces
            parts = re.split(r'\s{2,}', line)
            if len(parts) == 2:
                key = parts[0].strip().lower()
                value = parts[1].strip()
                
                if key == "architecture":
                    metadata['architecture'] = value
                elif key == "parameters":
                    metadata['parameters'] = value
                elif "context length" in key:
                    try:
                        metadata['context_length'] = int(value)
                    except ValueError:
                        metadata['context_length'] = None
                        print(f"Warning: Could not parse context length '{value}' for model {model_name}")
                elif "embedding length" in key:
                    try:
                        metadata['embedding_length'] = int(value)
                    except ValueError:
                        metadata['embedding_length'] = None
                        print(f"Warning: Could not parse embedding length '{value}' for model {model_name}")
                elif key == "quantization":
                    metadata['quantization'] = value
        
        # Parse parameters section
        elif section == "parameters":
            parts = line.split(None, 1)
            if len(parts) == 2:
                key, value = parts
                if key == "stop":
                    # Remove quotes if present
                    clean_value = value.strip('"')
                    metadata['stop_tokens'].append(clean_value)
        
        # Parse license section
        elif section == "license":
            metadata['license_text'] += line + "\n"
            
            # Try to extract release date
            date_match = re.search(r'Release Date: (\w+ \d+, \d{4})', line)
            if date_match:
                try:
                    date_str = date_match.group(1)
                    date_obj = datetime.strptime(date_str, '%B %d, %Y')
                    metadata['release_date'] = date_obj.strftime('%Y-%m-%d')
                except ValueError:
                    pass
    
    # Convert stop tokens to JSON string
    metadata['stop_tokens'] = json.dumps(metadata['stop_tokens'])
    
    return metadata

def insert_or_update_metadata(conn, metadata):
    """Insert or update model metadata in the database."""
    cursor = conn.cursor()
    
    # Check if model already exists
    cursor.execute("SELECT 1 FROM model_metadata WHERE model_name = %s", (metadata['model_name'],))
    exists = cursor.fetchone() is not None
    
    if exists:
        # Update existing record
        query = """
        UPDATE model_metadata SET
            architecture = %s,
            parameters = %s,
            context_length = %s,
            embedding_length = %s,
            quantization = %s,
            stop_tokens = %s,
            license_text = %s,
            release_date = %s,
            updated_at = NOW()
        WHERE model_name = %s
        """
        cursor.execute(query, (
            metadata['architecture'],
            metadata['parameters'],
            metadata['context_length'],
            metadata['embedding_length'],
            metadata['quantization'],
            metadata['stop_tokens'],
            metadata['license_text'],
            metadata['release_date'],
            metadata['model_name']
        ))
        print(f"Updated metadata for model: {metadata['model_name']}")
    else:
        # Insert new record
        query = """
        INSERT INTO model_metadata (
            model_name, architecture, parameters, context_length, 
            embedding_length, quantization, stop_tokens, 
            license_text, release_date
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query, (
            metadata['model_name'],
            metadata['architecture'],
            metadata['parameters'],
            metadata['context_length'],
            metadata['embedding_length'],
            metadata['quantization'],
            metadata['stop_tokens'],
            metadata['license_text'],
            metadata['release_date']
        ))
        print(f"Inserted metadata for model: {metadata['model_name']}")
    
    conn.commit()
    cursor.close()

def main():
    """Main function to get all models and their metadata."""
    args = parse_args()
    
    # Connect to database
    try:
        conn = mysql.connector.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            database=args.database
        )
    except mysql.connector.Error as e:
        print(f"Database connection error: {e}")
        sys.exit(1)
    
    print("Connected to database successfully")
    
    # Get all models
    models = get_all_models()
    if not models:
        print("No Ollama models found. Make sure Ollama is running.")
        conn.close()
        sys.exit(1)
    
    print(f"Found {len(models)} models. Retrieving metadata...")
    
    # Process each model
    for model in models:
        print(f"Processing model: {model}")
        try:
            metadata = parse_model_metadata(model)
            if metadata:
                insert_or_update_metadata(conn, metadata)
            else:
                print(f"Failed to retrieve metadata for model: {model}")
        except Exception as e:
            print(f"Error processing model {model}: {e}")
            continue
    
    conn.close()
    print("Processing complete")

if __name__ == "__main__":
    main()