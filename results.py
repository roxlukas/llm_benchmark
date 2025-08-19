import mysql.connector
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import argparse

def visualize_benchmark_results(db_config):
    """
    Generate visualizations from benchmark results.
    
    Args:
        db_config: Dictionary with MySQL connection parameters
    """
    try:
        # Connect to database
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        
        # Get model performance data
        query = """
            SELECT model, 
                   AVG(total_duration) as avg_duration,
                   AVG(eval_count) as avg_eval_count
            FROM benchmark_results
            WHERE success = 1
            GROUP BY model
        """
        cursor.execute(query)
        model_perf = pd.DataFrame(cursor.fetchall())
        
        # Get category performance by model
        query = """
            SELECT p.category, r.model,
                   AVG(total_duration) as avg_duration
            FROM benchmark_results r
            JOIN prompts p ON r.prompt_id = p.id
            WHERE r.success = 1
            GROUP BY p.category, r.model
        """
        cursor.execute(query)
        category_perf = pd.DataFrame(cursor.fetchall())
        
        # Create a directory for the visualizations
        import os
        os.makedirs("benchmark_results", exist_ok=True)
        
        # Plot model performance
        plt.figure(figsize=(12, 6))
        
        # Duration plot
        plt.subplot(1, 2, 1)
        sns.barplot(x='model', y='avg_duration', data=model_perf)
        plt.title('Average Response Time by Model')
        plt.xlabel('Model')
        plt.ylabel('Average Duration (seconds)')
        plt.xticks(rotation=45)
        
        # Eval count plot
        plt.subplot(1, 2, 2)
        sns.barplot(x='model', y='avg_eval_count', data=model_perf)
        plt.title('Average Evaluation Count by Model')
        plt.xlabel('Model')
        plt.ylabel('Average Eval Count')
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        plt.savefig('benchmark_results/model_performance.png')
        
        # Category performance by model
        plt.figure(figsize=(14, 8))
        sns.barplot(x='category', y='avg_duration', hue='model', data=category_perf)
        plt.title('Average Response Time by Category and Model')
        plt.xlabel('Category')
        plt.ylabel('Average Duration (seconds)')
        plt.xticks(rotation=45)
        plt.legend(title='Model')
        plt.tight_layout()
        plt.savefig('benchmark_results/category_performance.png')
        
        # Close database connection
        cursor.close()
        conn.close()
        
        print("Visualizations generated in benchmark_results/ directory")
        
    except Exception as e:
        print(f"Error generating visualizations: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='LLM Benchmark Results Visualizer')
    parser.add_argument('--host', default='localhost', help='MySQL host')
    parser.add_argument('--port', type=int, default=3306, help='MySQL port')
    parser.add_argument('--user', required=True, help='MySQL username')
    parser.add_argument('--password', required=True, help='MySQL password')
    parser.add_argument('--database', required=True, help='MySQL database name')
    
    args = parser.parse_args()
    
    db_config = {
        'host': args.host,
        'port': args.port,
        'user': args.user,
        'password': args.password,
        'database': args.database
    }
    
    visualize_benchmark_results(db_config)