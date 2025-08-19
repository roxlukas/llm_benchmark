# LLM Benchmark

System do benchmarkowania i wizualizacji wyników modeli językowych LLM.

## Opis projektu

Projekt składa się z dwóch głównych komponentów:
- **Benchmark (Python)** - `benchmark.py` - narzędzie do uruchamiania testów na modelach LLM
- **Wizualizacja (PHP)** - pliki `.php` - interfejs webowy do przeglądania i porównywania wyników

## Wymagania systemowe

### Python
- Python 3.x
- Biblioteki: `mysql-connector-python`, `requests`

### PHP
- PHP 7.4+ z rozszerzeniem PDO MySQL
- Serwer MySQL/MariaDB
- Serwer web (Apache/Nginx)

### Ollama (opcjonalnie)
- Ollama API działające na `http://localhost:11434`

## Instalacja i konfiguracja

### 1. Konfiguracja bazy danych

1. Utwórz bazę danych MySQL:
```sql
mysql -u root -p < schema.sql
```

2. Stwórz użytkownika bazy danych:
```sql
CREATE USER 'llmuser'@'localhost' IDENTIFIED BY 'SuperSecretPassword#175';
GRANT ALL PRIVILEGES ON llm_benchmark.* TO 'llmuser'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Konfiguracja PHP

1. Skopiuj plik konfiguracyjny:
```bash
cp config-dist.php config.php
```

2. Edytuj `config.php` i ustaw parametry bazy danych:
```php
$dbConfig = [
    'host' => '192.168.1.2',
    'port' => 3306,
    'user' => 'llmuser',
    'password' => 'SuperSecretPassword#175',
    'database' => 'llm_benchmark'
];
```

### 3. Konfiguracja Python

Utwórz plik `.env` w katalogu głównym:
```
GEMINI_API_KEY="AI12345678901234567890ABCDEFABCDEF"
```

### 4. Instalacja zależności Python

```bash
pip install mysql-connector-python requests dotenv
```

## Uruchomienie

### Benchmark (Python)
```bash
python benchmark.py --host 192.168.1.2 --port 3306 --user llmuser --password SuperSecretPassword#175 --database llm_benchmark --ollama http://192.168.1.2:11434
python model_metadata.py --host 192.168.1.2 --port 3306 --user llmuser --password SuperSecretPassword#175 --database llm_benchmark 
python gemini_evaluate.py --host 192.168.1.2 --port 3306 --user llmuser --password SuperSecretPassword#175 --database llm_benchmark
```

### Wizualizacja (PHP)
Uruchom serwer web i otwórz `index.php` w przeglądarce.

Dostępne pliki wizualizacji:
- `index.php` - główna tabela porównawcza wyników
- `graphs.php` - wykresy i statystyki
- `ajax.php` - API do dynamicznego ładowania danych

## Struktura plików

- `benchmark.py` - główny skrypt benchmarkowy
- `config-dist.php` - szablon konfiguracji PHP
- `config.php` - plik konfiguracyjny PHP (tworzony z dist)
- `schema.sql` - schemat bazy danych
- `index.php` - główny interfejs webowy
- `graphs.php` - wizualizacje graficzne
- `ajax.php` - endpoint API
- `model_metadata.py` - metadane modeli
- `results.py` - analiza wyników
- Pliki `.bat` - skrypty Windows do automatyzacji

## Bezpieczeństwo

- **NIGDY** nie commituj pliku `config.php` do repozytorium
- Upewnij się, że plik `.env` jest dodany do `.gitignore`
- Używaj silnych haseł dla bazy danych
- Ogranicz dostęp do plików konfiguracyjnych na serwerze