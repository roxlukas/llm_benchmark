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

`lotus_game/index.html` to wyścig pseudo-3D w HTML5 (canvas, bez zależności): zakręty, wzniesienia, 11 rywali, drzewa i znaki przy drodze, limit czasu 150 s. Jak w oryginalnym Lotusie po uderzeniu w drzewo lub znak auto stoi 3 s (zegar leci) i wraca na skraj drogi po tej stronie, po której z niej zjechało (zasady gry v3; `game_version` w wynikach). Można w niego zagrać w przeglądarce (strzałki, Spacja start, `A` włącza autopilota, `?seed=N` zmienia trasę).

`game_benchmark.py` uruchamia grę headless (Playwright) i co `--hold` klatek (domyślnie 6 = 0,1 s) wysyła zrzut canvasu do `/v1/systemone` z pytaniem `choice`: `left` / `straight` / `right` / `brake`. Czas gry płynie tylko między decyzjami, więc wolny model jedzie ten sam wyścig co szybki; `--realtime` każe mu trzymać poprzednią akcję tak długo, jak trwała decyzja.

```bash
pip install playwright
python game_benchmark.py --models oracle,random,straight                 # punkty odniesienia, bez serwera
python game_benchmark.py --models d3:4b,d3:9b                            # modele decyzyjne z wizją w Ollamie (obraz w "images")
python game_benchmark.py --api basal --models basal-omni-1.0-mini        # basal-serve --mode eager --media on (obraz w "media")
python game_benchmark.py --models d3:4b --seeds 1 --save-frames --headed # podgląd na żywo + klatki i GIF z przejazdu
```

basal-omni w GGUF (Ollama) widzi tylko tekst: enkodery obrazu są wycięte z plików GGUF. Obrazy czyta wersja bf16 przez `basal-serve --model D:/AI/basal/basal-omni-1.0-mini --mode eager --media on --port 8000`.

basal-omni-1.0-max w bf16 (~24 GB) nie mieści się na RTX 3090. Jeździ checkpoint FP8 (`Remek/basal-omni-1.0-max-FP8`, 13 GB) przez vLLM w WSL i basal ≥ 2.5 (obrazy dla modeli Gemma 4 Unified w `--mode vllm`). Na Ampere vLLM używa jądra Marlin (wagi FP8, obliczenia bf16). W checkpoincie trzeba dopisać `model.vision_embedder*` do `quantization_config.ignore` w `config.json` i do `exclude_modules` w `hf_quant_config.json`, inaczej vLLM ładuje wagi bf16 `vision_embedder.patch_dense` jako FP8 i każde zapytanie z obrazem kończy się NaN.

```bash
basal-serve --model ~/models/basal-omni-1.0-max-FP8 --mode vllm --media on --gpu-memory 0.88 --max-len 8192 --port 8000   # w WSL
python game_benchmark.py --api basal --models basal-omni-1.0-max-FP8                                                    # w Windows
```

Do serwera w WSL łącz się przez `127.0.0.1`, nie `localhost`: `localhost` najpierw próbuje IPv6 i każde zapytanie traci ~2 s.

Wynik (`game_results.json`): `score` = 100 × ukończona część trasy + do 50 pkt za szybki finisz − 2 za każde zderzenie z autem − 5 za każde uderzenie w drzewo/znak. Do tego czas, pozycja, średnia prędkość, % klatek poza drogą, zgodność z autopilotem (`oracle`, który czyta stan gry, nie obraz) i opóźnienie decyzji. Logi każdej decyzji: `game_runs/<run_id>/`.

`straight` (pełny gaz, nigdy nie skręca) to dolna granica: `score_vs_straight` (kolumna `vs str`) to wynik modelu minus wynik `straight` przy tych samych ustawieniach i zasadach. Model z wynikiem ≤ 0 nie steruje z obrazu lepiej niż brak sterowania. Na zasadach v3: `oracle` 128,8, `straight` 26,8 (1/3 ukończone), `random` 20,6. Na v2 (kara 1,5 s) `straight` kończył każdą trasę i miał tyle samo co basal-omni-1.0-mini (58,0 vs 58,2), stąd zaostrzenie.

Film z przejazdu (wymaga przebiegu z `--save-frames` i ffmpeg): pod każdą klatką decyzja modelu, jej prawdopodobieństwa, akcja autopilota i czas decyzji; między trasami plansze z wynikiem.

```bash
python game_video.py game_runs/<run_id> --ffmpeg D:/ffmpeg.exe   # game_runs/<run_id>/<model>.mp4
```
