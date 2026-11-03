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

`publish_to_site.py` kopiuje `results.json`, `decision_results.json` (modele decyzyjne, zestaw v1) i `decision_results_v2.json` (trudniejszy zestaw v2, `decision_data_v2/`) do repozytorium strony (`wwwroot/llm-benchmark/`), robi gałąź od `origin/main` w tymczasowym worktree (Twój katalog roboczy strony zostaje nietknięty), wypycha ją i otwiera PR przez `gh`. Merge robisz sam.

```bash
python publish_to_site.py --site-dir C:/htdocs/aitransformation.pl --refresh   # odśwież JSON z bazy i opublikuj wszystkie pliki
python publish_to_site.py --only decisions --dry-run                            # tylko sprawdź i pokaż różnice
python publish_to_site.py --only decisions_v2 --refresh                         # tylko v2: decision_benchmark.py --data-dir decision_data_v2 --report
```

`--site-dir` można zastąpić zmienną `SITE_REPO` (też w `.env`). Przed publikacją plik jest sprawdzany: poprawny JSON, wymagane pola, brak NaN i nie mniej modeli niż w opublikowanej wersji (`--allow-fewer-models` to wyłącza). Wymaga `git` i `gh` (zalogowanego do repozytorium strony). Testy: `python -m unittest test_publish_to_site`.

## Benchmark wizualny: wyścig (klon Lotus Esprit Turbo Challenge)

`lotus_game/index.html` to wyścig pseudo-3D w HTML5 (canvas, bez zależności): zakręty, wzniesienia, 11 rywali, drzewa i znaki przy drodze, limit czasu 150 s. Można w niego zagrać w przeglądarce (strzałki, Spacja start, `A` włącza autopilota, `?seed=N` zmienia trasę).

`game_benchmark.py` uruchamia grę headless (Playwright) i co `--hold` klatek (domyślnie 6 = 0,1 s) wysyła zrzut canvasu do `/v1/systemone` z pytaniem `choice`: `left` / `straight` / `right` / `brake`. Czas gry płynie tylko między decyzjami, więc wolny model jedzie ten sam wyścig co szybki; `--realtime` każe mu trzymać poprzednią akcję tak długo, jak trwała decyzja.

```bash
pip install playwright
python game_benchmark.py --models oracle,random                          # punkty odniesienia, bez serwera
python game_benchmark.py --models d3:4b,d3:9b                            # modele decyzyjne z wizją w Ollamie (obraz w "images")
python game_benchmark.py --api basal --models basal-omni-1.0-mini        # basal-serve --mode eager --media on (obraz w "media")
python game_benchmark.py --models d3:4b --seeds 1 --save-frames --headed # podgląd na żywo + klatki i GIF z przejazdu
```

basal-omni w GGUF (Ollama) widzi tylko tekst: enkodery obrazu są wycięte z plików GGUF. Obrazy czyta wersja bf16 przez `basal-serve --model D:/AI/basal/basal-omni-1.0-mini --mode eager --media on --port 8000`.

Wynik (`game_results.json`): `score` = 100 × ukończona część trasy + do 50 pkt za szybki finisz − 2 za każde zderzenie z autem − 5 za każde uderzenie w drzewo/znak. Do tego czas, pozycja, średnia prędkość, % klatek poza drogą, zgodność z autopilotem (`oracle`, który czyta stan gry, nie obraz) i opóźnienie decyzji. Logi każdej decyzji: `game_runs/<run_id>/`.
