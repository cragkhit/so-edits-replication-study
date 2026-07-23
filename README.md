# SO Edits Replication Study (Python)

Scripts and pipeline for a Python replication study using Siamese+ (i.e., Matcha -- the
Siamese-based code clone search tool), covering: finding and cloning Python
GitHub repos, indexing a large Python snippet corpus, and searching each
cloned repo's code against that index.

The Matcha tool itself lives in a separate repo — see setup below.

## Setup: getting and building Matcha

Matcha's own repo is at **github.com/cragkhit/Matcha**. This study's
Python-specific additions (Python config, Python boilerplate patterns,
a couple of reliability fixes) live on the **`python-clone-search-study`**
branch.

```bash
git clone https://github.com/cragkhit/Matcha.git
cd Matcha
git checkout python-clone-search-study
```

### 1. Install Java 8

Matcha and its bundled Elasticsearch 2.2.0 (2016) predate modern Java by a
wide margin and hit real incompatibilities on JDK 9+ (see "Known issues"
below). Install Eclipse Temurin 8:

```bash
brew install --cask temurin@8
# or, without sudo: download a plain tarball build from adoptium.net
# and extract it to /Library/Java/JavaVirtualMachines/
```

### 2. Set up Elasticsearch 2.2.0

```bash
wget https://download.elasticsearch.org/elasticsearch/release/org/elasticsearch/distribution/tar/elasticsearch/2.2.0/elasticsearch-2.2.0.tar.gz
tar -xvf elasticsearch-2.2.0.tar.gz
```

Add to `elasticsearch-2.2.0/config/elasticsearch.yml`:
```yaml
cluster.name: stackoverflow
index.query.bool.max_clause_count: 20480
```

Patch `elasticsearch-2.2.0/bin/elasticsearch.in.sh` to remove the
`-XX:+UseParNewGC` flag (removed in JDK 9+; keep `-XX:+UseConcMarkSweepGC`).

Start it under Java 8, with enough heap for a multi-million-document index:
```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home
export ES_HEAP_SIZE=4g
./elasticsearch-2.2.0/bin/elasticsearch -d
```

### 3. Build Matcha

```bash
export JAVA_HOME=/Library/Java/JavaVirtualMachines/temurin-8.jdk/Contents/Home
mvn -DskipTests compile package
cp target/matcha-0.1.0.jar .
```

### 4. Configure

Edit `config_python.properties` (already included on the
`python-clone-search-study` branch) and set at least:
```properties
elasticsearchLoc=/path/to/elasticsearch-2.2.0
index=python_files
inputFolder=/path/to/python/corpus/to/index
outputFolder=search_results
boilerplateCodePatternFile=/path/to/Matcha/references/BoilerPlateConfig_python.txt
```

### Known issues fixed on the `python-clone-search-study` branch

- **`AccessControlException` on every flush (JDK 9+):** Lucene 5.4.1's
  `MMapDirectory` unmap hack targets `sun.misc.Cleaner`, which moved to
  `jdk.internal.ref.Cleaner` on JDK 9+. ES's bundled security policy never
  granted access to the new package, so every index flush/commit failed,
  shards went red, and writes timed out. Fixed by running on Java 8 (§1–2
  above) instead of patching the security policy.
- **Fatal `StackOverflowError` on pathologically nested input:** one
  deeply-nested file can blow the ANTLR parser's recursion stack. This was
  fatal because `Main.java`/`Siamese.java` only caught `Exception`, not
  `Throwable`/`Error`, crashing the entire (multi-hour) indexing run instead
  of skipping the one bad file. Fixed by broadening those catch blocks to
  `Throwable` and launching with `-Xss16m` for extra recursion headroom.
- **`boilerplateCodePatternFile` missing/wrong for Python:** the stock
  config pointed at a Java-only pattern file (`^toString()$`, `on[A-Z]*`,
  etc.) that doesn't match Python function names and doesn't exist at its
  configured path — caused a `NullPointerException` on every search. Fixed
  by adding `references/BoilerPlateConfig_python.txt` with Python-appropriate
  patterns (dunder methods, `get_`/`set_`/`is_` prefixes, `to_dict`, common
  framework callback names) and pointing the config at it.

## Pipeline (this repo's scripts)

### 1. Find Python GitHub repos to clone

`find_python_repos.py` — stdlib-only script using GitHub's Search API to
find repos matching: Python, ≥10 stars, not a fork, has open issues, has
open PRs. Supports `--max-stars` to page past the Search API's 1000-result
cap, and `--append` to dedup across batches. Needs a GitHub token
(`GITHUB_TOKEN` env var) for a reasonable rate limit.

```bash
export GITHUB_TOKEN=ghp_xxxx
python3 find_python_repos.py --limit 1000 --min-stars 10 --output repos.txt
```

Result: **`repos.txt`** — 1,000 matching repo URLs.

### 2. Clone repos

`clone_repos.py` — clones repos listed in `repos.txt`.

```bash
python3 clone_repos.py --num 100 --dest python_repos_100
```

Key flags: `--num N` (how many to clone, default: all), `--depth` (shallow
clone depth, default 1), `--jobs` (parallel clones).

### 3. Index a Python corpus

From the Matcha checkout:
```bash
java -jar matcha-0.1.0.jar -cf config_python.properties -c index
```

Note on index size vs. source size: the resulting index is much smaller
than the source corpus because (a) raw source text is deliberately not
stored (a performance choice in `insert()`), (b) only tokenized/normalized
representations are kept, which compress far better than raw text, (c)
files that fail to parse contribute nothing, and (d) methods under
`minCloneSize` are dropped.

### 4. Search cloned repos against the index

`search_all_repos.sh` (lives on Matcha's `python-clone-search-study` branch)
loops over every repo dir in `python_repos_100/`, runs a Matcha search using
each one as the query input, and saves the result renamed to
`<repo-name>_<timestamp>.csv`:

```bash
cd Matcha
./search_all_repos.sh
```

Note: some result files may be legitimately empty — that means no code in
the index cleared the similarity threshold for that repo's methods, not a
bug.

## Run log

Actual timing from running this pipeline end-to-end:

| Run | Started | Ended | Duration |
|---|---|---|---|
| Indexing (2,915,926 files → 387,020 methods) | — | — | ~5h8m (across restarts; see "Known issues" above) |
| Searching 100 cloned repos against the index | 2026-07-23 04:42:11 | 2026-07-23 17:49:59 | ~12h14m active search time (~13h8m wall-clock span). The run was killed unexpectedly partway through (after 47 repos) and resumed via `search_all_repos.sh`'s skip-if-already-processed logic, so the total spans two segments (5h23m + 6h51m) with a ~54min gap in between. |

Final search results: **100/100 repos processed, 63 with at least one match above the similarity threshold, 37 with none** (legitimate no-match results, not errors).

### Watch progress

`watch_index_progress.sh` — tails an indexing/search log, filtered to just
the progress lines.

```bash
./watch_index_progress.sh /path/to/log/file
```

## Files in this repo

| Path | What |
|---|---|
| `find_python_repos.py` | Discover qualifying Python GitHub repos |
| `clone_repos.py` | Clone N repos from `repos.txt` |
| `watch_index_progress.sh` | Tail an indexing/search log, filtered to progress lines |
| `repos.txt` | 1,000 discovered GitHub Python repo URLs |

Large/generated artifacts (the cloned repos, the indexed corpus, Elasticsearch
itself, search result CSVs) are intentionally not tracked in this repo — see
`.gitignore`.
