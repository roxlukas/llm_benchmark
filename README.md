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

### 2. Konfiguracja (`.env`)

Hasło do bazy i klucze API są tylko w pliku `.env` (nie trafia do repozytorium). Czytają go zarówno skrypty Python, jak i strony PHP (`config.php`).

```bash
cp .env.example .env
```

Uzupełnij w `.env` co najmniej `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` oraz klucze ewaluatora. Na serwerze z PHP `DB_HOST` to zwykle `localhost`, a na komputerze, z którego uruchamiasz skrypty Python, adres serwera bazy.

`.htaccess` blokuje pobranie `.env` przez Apache. Na Nginx dodaj odpowiednią regułę (`location ~ /\.env { deny all; }`).

### 4. Instalacja zależności Python

```bash
pip install mysql-connector-python requests python-dotenv
```

## Uruchomienie

### Benchmark (Python)
```bash
python benchmark.py --ollama http://192.168.1.2:11434
python model_metadata.py
python gemini_evaluate.py
python export_json.py
```

Parametry bazy pochodzą z `.env`. Flagi `--host`, `--port`, `--user`, `--password`, `--database` nadal działają i nadpisują `.env` (np. `--database llm_benchmark_mistral_telco`).

### Wizualizacja (PHP)
Uruchom serwer web i otwórz `index.php` w przeglądarce.

Dostępne pliki wizualizacji:
- `index.php` - główna tabela porównawcza wyników
- `graphs.php` - wykresy i statystyki
- `ajax.php` - API do dynamicznego ładowania danych

## Struktura plików

- `benchmark.py` - główny skrypt benchmarkowy
- `.env.example` - szablon `.env` (hasło do bazy, klucze API)
- `config.php` - konfiguracja PHP, czyta `.env`
- `db_env.py` - wspólne parametry bazy dla skryptów Python, czyta `.env`
- `schema.sql` - schemat bazy danych
- `index.php` - główny interfejs webowy
- `graphs.php` - wizualizacje graficzne
- `ajax.php` - endpoint API
- `model_metadata.py` - metadane modeli
- `results.py` - analiza wyników
- Pliki `.bat` - skrypty Windows do automatyzacji

## Bezpieczeństwo

- **NIGDY** nie commituj pliku `.env` (jest w `.gitignore`) ani nie wpisuj haseł do plików `.php`, `.py` i `.bat`
- Upewnij się, że serwer web nie serwuje pliku `.env`
- Używaj silnych haseł dla bazy danych
- Ogranicz dostęp do plików konfiguracyjnych na serwerze


## Publikacja wyników na aitransformation.pl

`publish_to_site.py` kopiuje `results.json` i `decision_results.json` do repozytorium strony (`wwwroot/llm-benchmark/`), robi gałąź od `origin/main` w tymczasowym worktree (Twój katalog roboczy strony zostaje nietknięty), wypycha ją i otwiera PR przez `gh`. Merge robisz sam.

```bash
python publish_to_site.py --site-dir C:/htdocs/aitransformation.pl --refresh   # odśwież JSON z bazy i opublikuj oba pliki
python publish_to_site.py --only decisions --dry-run                            # tylko sprawdź i pokaż różnice
```

`--site-dir` można zastąpić zmienną `SITE_REPO` (też w `.env`). Przed publikacją plik jest sprawdzany: poprawny JSON, wymagane pola, brak NaN i nie mniej modeli niż w opublikowanej wersji (`--allow-fewer-models` to wyłącza). Wymaga `git` i `gh` (zalogowanego do repozytorium strony). Testy: `python -m unittest test_publish_to_site`.
