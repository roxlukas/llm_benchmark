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

## Benchmark embeddingów: wyszukiwanie w dokumentacji (EN + PL)

Korpus to Pomoc LibreOffice (`help.libreoffice.org/latest`): te same 911 stron po angielsku (en-US) i po polsku (pl), pocięte na fragmenty według nagłówków h1/h2 (do 1500 znaków). Wychodzi 3101 fragmentów EN i 3200 PL. Na każdy język przypada 500 zapytań, każde z innej strony. Zapytania wygenerował lokalnie `mistral-small3.2:24b`, czyli model spoza rodzin testowanych embedderów. Każde zapytanie ma jeden złoty fragment, a style są trzy po równo: `goal` (cel opisany bez nazwy funkcji czy menu), `keyword` (krótka fraza wyszukiwania) i `howto` (konkretne pytanie o szczegół).

Każdy model ma w każdym języku osobną kolekcję `embbench_<lang>_<model>` w osobnej instancji Qdrant na NIAGARA: `D:\AI\qdrant-embedbench`, port 6343, nasłuch tylko na 127.0.0.1. Prefiksy zapytań i dokumentów są takie, jak zaleca karta modelu (`MODELS` w `embedding_benchmark.py`). `bm25` (Python, bez stemmingu) to dolna granica.

```bash
D:\AI\qdrant-embedbench\qdrant.exe --config-path D:\AI\qdrant-embedbench\config\config.yaml   # uruchom w tym katalogu
python embedding_corpus.py                       # pobiera strony (cache: embedding_data/raw/, poza gitem) -> embedding_data/<lang>/corpus.jsonl
python embedding_queries.py --n 500              # -> embedding_data/<lang>/queries.jsonl (wznawia przerwane)
python embedding_benchmark.py                    # wszystkie modele -> embedding_results.json, rangi zapytań: embedding_runs/<run_id>/
python embedding_benchmark.py --models bge-m3:latest --langs pl --reindex
```

Metryki: Hit@1/5/10, MRR@10 i nDCG@10 dla złotego fragmentu. Do tego `pgH@k`: trafienie, jeśli w top-k jest dowolny fragment złotej strony.

Wyniki z 2026-11-12 (MRR@10 na poziomie fragmentu; RTX 3090 przy nominalnych 350 W):

| model | EN MRR | EN Hit@10 | PL MRR | PL Hit@10 | wymiar | doc/s |
|---|---|---|---|---|---|---|
| qwen3-embedding:8b | **78,4** | **96,0** | **73,2** | **94,4** | 4096 | 12–17 |
| qwen3-embedding:4b | 74,7 | 95,4 | 70,8 | 93,8 | 2560 | 20–26 |
| embeddinggemma (v1, 300m) | 71,2 | 89,8 | 70,8 | 90,0 | 768 | ~51 |
| snowflake-arctic-embed2 | 71,0 | 90,2 | 71,6 | 90,4 | 1024 | ~47 |
| qwen3-embedding:0.6b | 69,6 | 90,4 | 63,6 | 85,8 | 1024 | ~44 |
| embeddinggemma-2 (każdy tag) | 68,0 | 87,8 | 64,6 | 88,0 | 768 | ~44 |
| nomic-embed-text-v2-moe | 67,8 | 87,8 | 65,6 | 87,4 | 768 | ~63 |
| bge-m3 | 65,5 | 86,6 | 68,3 | 88,6 | 1024 | ~45 |
| granite-embedding:278m | 64,8 | 86,8 | 57,6 | 77,0 | 768 | ~67 |
| mxbai-embed-large (tylko EN) | 66,0 | 84,8 | 30,1 | 48,2 | 1024 | ~49 |
| nomic-embed-text (v1, tylko EN) | 62,7 | 83,0 | 39,1 | 57,2 | 768 | ~72 |
| bm25 | 62,2 | 83,2 | 54,1 | 78,6 | – | – |
| paraphrase-multilingual | 49,3 | 73,4 | 41,6 | 62,6 | 768 | ~79 |

- Tagi `embeddinggemma-2:270m/440m/570m/740m` w Ollamie mają ten sam model tekstowy 271M (ten sam blob, wektory identyczne bit w bit). Większe tagi dokładają tylko enkodery obrazu (440m), audio (570m) albo obu (740m). Do tekstu wystarczy `270m`.
- embeddinggemma-2 wypada gorzej od embeddinggemma v1: −3,1 MRR po angielsku (95% CI [+0,9; +5,5] na korzyść v1) i −6,2 po polsku ([+3,3; +8,8]). Inny format prefiksu nic nie daje: `title: <tytuł>` w miejscu `title: none` zmienia wynik o ±1, a brak prefiksów obniża go o 2–3 pkt.
- Przewaga qwen3-embedding:8b pochodzi głównie z zapytań `goal`, czyli opisu celu bez nazwy funkcji: 74,7 EN / 67,0 PL wobec ~60 u modeli 300M–600M. Po polsku jego różnica do snowflake-arctic-embed2 (+1,6) mieści się w szumie (CI [−1,4; +4,9]).
- Najlepszy stosunek jakości do kosztu w obu językach mają embeddinggemma v1 i snowflake-arctic-embed2: ok. 71 MRR i ~50 doc/s.
- Wynik HNSW w Qdrancie zgadza się z dokładnym przeszukaniem w numpy (sprawdzone na embeddinggemma-2), więc przybliżone wyszukiwanie niczego nie gubi.
- Zapytania pisał LLM, który widział fragment, więc część zapytań `howto` powtarza słowa z tekstu. Dlatego BM25 wypada w nich mocno (76 EN), a słabo w `goal` (43 EN).
