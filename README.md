# Matcha Study — Setup & Pipeline Log

This documents the steps taken in this working directory to get Matcha
(the Siamese-based code clone search tool) running locally, indexed with a
large Python corpus, and used to search against 100 real GitHub repos.

## 1. Getting the project

Downloaded `/root/matcha_study/1_matcha` from a remote server (103.114.202.228)
via `rsync` over SSH into `1_matcha/`.

## 2. Elasticsearch 2.2.0 setup

Matcha runs on Elasticsearch 2.2.0 (2016), which predates modern Java by a
wide margin. Two separate Java-version incompatibilities had to be fixed:

- **`UseParNewGC` removed (JDK 9+):** the default Mac Java (Homebrew's JDK 23)
  doesn't support the hardcoded GC flags. Patched
  `elasticsearch-2.2.0/bin/elasticsearch.in.sh` to drop `-XX:+UseParNewGC`
  (kept `-XX:+UseConcMarkSweepGC`, valid through JDK 13).
- **`AccessControlException` on every flush (JDK 9+):** Lucene 5.4.1's
  `MMapDirectory` unmap hack targets `sun.misc.Cleaner`, which moved to
  `jdk.internal.ref.Cleaner` on JDK 9+. ES's bundled security policy never
  granted access to the new package, so every index flush/commit failed,
  shards went red, and writes timed out. **Fixed by installing Java 8**
  (Eclipse Temurin 8, downloaded as a plain tarball extracted to
  `/Library/Java/JavaVirtualMachines/temurin-8.jdk`, no `sudo` needed) and
  running Elasticsearch under it instead.

`elasticsearch-2.2.0/start-es.sh` wraps startup, pinning `JAVA_HOME` to the
Java 8 install. Elasticsearch heap was bumped to 4GB (`ES_HEAP_SIZE=4g`) to
handle indexing millions of documents.

Start it with:
```bash
cd elasticsearch-2.2.0
export ES_HEAP_SIZE=4g
./start-es.sh -d
```

## 3. Python-language config

`1_matcha/config_python.properties` — a Matcha config for Python (the
project ships only a Java config by default). Points `methodParser`,
`tokenizer`, `normalizer`, `normalizerMode` at the `crest.siamese.language.python3.*`
classes, sets `extension=py`, and uses Python-appropriate normalization
modes (`t2NormMode=vsw`, `t3NormMode=kvsow`).

QR (query reduction) thresholds were tuned to the optimized values from a
reference paper's Table 3: `QRPercentileOrig=9`, `QRPercentileT1=6`,
`QRPercentileT2=5`, `QRPercentileNorm=9` (clone size, n-gram size, and
similarity thresholds were already at their optimal defaults).

`boilerplateCodePatternFile` originally pointed at the Java-only
`references/BoilerPlateConfig.txt` (patterns like `^toString()$`, `on[A-Z]*`)
which don't match Python function names and don't even exist at that path
locally — caused a `NullPointerException` on every search. Fixed by writing
`references/BoilerPlateConfig_python.txt` with Python-appropriate patterns
(dunder methods, `get_`/`set_`/`is_` prefixes, `to_dict`/`from_dict`, common
framework callback names, etc.) and pointing the config at it instead.

## 4. Finding Python GitHub repos to clone

`find_python_repos.py` — stdlib-only script using GitHub's Search API to
find repos matching: Python, ≥10 stars, not a fork, has open issues, has
open PRs. Supports `--max-stars` to page past the Search API's 1000-result
cap, and `--append`/dedup to dothis in batches. Needs a GitHub token
(`GITHUB_TOKEN` env var) for a reasonable rate limit.

Result: **`repos.txt`** — 1,000 matching repo URLs (924 from the first
1000-result page, 76 more from a second batch bounded by
`stars:10..9792` to page past the cap).

## 5. Cloning repos

`clone_repos.py` — clones repos listed in `repos.txt`. Key flag:
`--num N` to control how many to clone (default: all). Shallow-clones by
default (`--depth 1`) to save space/time; supports parallel cloning
(`--jobs`).

Cloned the first 100 into **`python_repos_100/`**.

## 6. Indexing the Python corpus

Indexed `python_files/` (2,915,926 `.py` files, ~11GB, a pre-existing
Stack-Overflow-derived snippet corpus) into Elasticsearch via:
```bash
java -jar matcha-0.1.0.jar -cf config_python.properties -c index
```

Two failures hit during this multi-hour job, both fixed:

- **Red cluster / `UnavailableShardsException`:** caused by the JDK 9+
  `AccessControlException` above — fixed by switching to Java 8 (see §2).
- **Fatal `StackOverflowError`, ~75% through (2.18M/2.9M files):** one
  pathologically deeply-nested file blew the ANTLR parser's recursion
  stack. This was fatal because `Main.java`/`Siamese.java` only caught
  `Exception`, not `Throwable`/`Error`, so it crashed the whole run instead
  of just skipping the bad file. **Fixed in source** (rebuilt via Maven,
  installed with `brew install maven`):
  - `Siamese.java`: both per-method and per-file `catch (Exception e)` in
    `insert()` broadened to `catch (Throwable e)`.
  - `Main.java`: added a top-level `catch (Throwable t)` safety net.
  - Re-run launched with `-Xss16m` for extra recursion headroom.

Final result: **`python_files` index, 387,020 methods indexed** from
2,915,926 source files, ~1GB index size (elapsed: ~5h8m of actual indexing
across the restarts).

Note on index size vs. source size: the index is much smaller than the
11GB source because (a) raw source text is deliberately not stored
(`originalSource` is always empty — a performance choice in `insert()`),
(b) only tokenized/normalized representations are kept, which compress far
better than raw text, (c) many files fail to parse (syntax errors/fragments)
and contribute nothing, and (d) methods under `minCloneSize` (6 lines) are
dropped.

## 7. Searching: one repo's code against the index

`1_matcha/search_all_repos.sh` — loops over every repo dir in
`python_repos_100/`, runs a Matcha search using each one as the query input:
```bash
java -jar matcha-0.1.0.jar -cf config_python.properties -c search -i <repo> -o search_results
```
then renames the resulting output file to `<repo-name>_<timestamp>.csv` in
`1_matcha/search_results/`. Logs progress to `1_matcha/search_all_repos.log`.

Run it with:
```bash
cd 1_matcha
./search_all_repos.sh
```

Note: some result files may be legitimately empty — that means no code in
the index cleared the similarity threshold (50–80% depending on
representation) for that repo's methods, not a bug. Verified the pipeline
itself is healthy by confirming the index has real, populated documents and
that `csvfline` output formatting works correctly when matches do exist.

## Useful scripts

| Script | Purpose |
|---|---|
| `elasticsearch-2.2.0/start-es.sh` | Start ES under Java 8 with a 4GB heap |
| `find_python_repos.py` | Discover qualifying Python GitHub repos |
| `clone_repos.py` | Clone N repos from `repos.txt` |
| `watch_index_progress.sh` | Tail the indexing log, filtered to progress lines |
| `1_matcha/search_all_repos.sh` | Search all cloned repos against the index, one at a time |

## Key config/data files

| Path | What |
|---|---|
| `1_matcha/config_python.properties` | Python-language Matcha config (indexing + search) |
| `1_matcha/references/BoilerPlateConfig_python.txt` | Python boilerplate method-name patterns |
| `repos.txt` | 1,000 discovered GitHub Python repo URLs |
| `python_repos_100/` | 100 cloned repos (query inputs) |
| `python_files/` | Source corpus that was indexed (2.9M files) |
| `1_matcha/search_results/` | Per-repo search result CSVs |
