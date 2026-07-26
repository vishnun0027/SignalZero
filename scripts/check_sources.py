"""Quick connectivity check for all SignalZero external data sources (stdlib only)."""
import json
import time
import urllib.request
import urllib.error
import urllib.parse

SOURCES = [
    {
        "name": "arXiv API",
        "url": "http://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=1",
        "used_for": "Paper ingestion (fetch_arxiv_papers)",
        "auth": "None required",
        "parse": "xml",
    },
    {
        "name": "Semantic Scholar API",
        "url": "https://api.semanticscholar.org/graph/v1/paper/arXiv:1706.03762?fields=citationCount,referenceCount",
        "used_for": "Citation enrichment (enrich_with_semantic_scholar)",
        "auth": "Optional: SEMANTIC_SCHOLAR_API_KEY",
        "parse": "json",
    },
    {
        "name": "HackerNews Algolia API",
        "url": "https://hn.algolia.com/api/v1/search?query=transformer&tags=story",
        "used_for": "Community signal detection (run_hn_detector)",
        "auth": "None required",
        "parse": "json",
    },
]

print("=" * 65)
print("  SignalZero — External Data Source Connectivity Check")
print("=" * 65)

for src in SOURCES:
    print(f"\n{'─' * 65}")
    print(f"  Source:    {src['name']}")
    print(f"  Used for: {src['used_for']}")
    print(f"  Auth:     {src['auth']}")
    print(f"  URL:      {src['url'][:70]}...")

    try:
        start = time.time()
        req = urllib.request.Request(src["url"], headers={"User-Agent": "SignalZero/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            elapsed = time.time() - start
            status = resp.status
            body = resp.read().decode("utf-8", errors="replace")

            if status == 200:
                print(f"  Status:   ✅ REACHABLE (HTTP {status}, {elapsed:.2f}s)")
                if src["parse"] == "json":
                    data = json.loads(body)
                    if src["name"] == "Semantic Scholar API":
                        print(f"  Sample:   citationCount={data.get('citationCount')}, refCount={data.get('referenceCount')}")
                    elif src["name"] == "HackerNews Algolia API":
                        hits = data.get("hits", [])
                        print(f"  Sample:   {len(hits)} stories found")
                        if hits:
                            print(f"  Top hit:  \"{hits[0].get('title', 'N/A')}\"")
                else:
                    print(f"  Sample:   {len(body)} bytes XML response")
            else:
                print(f"  Status:   ⚠️  HTTP {status} ({elapsed:.2f}s)")

    except urllib.error.HTTPError as e:
        elapsed = time.time() - start
        if e.code == 429:
            print(f"  Status:   ⚠️  RATE LIMITED (HTTP 429, {elapsed:.2f}s)")
            print(f"            API is reachable but you're being throttled.")
        else:
            print(f"  Status:   ❌ HTTP ERROR {e.code} ({elapsed:.2f}s)")
    except urllib.error.URLError as e:
        print(f"  Status:   ❌ CONNECTION FAILED: {e.reason}")
    except TimeoutError:
        print(f"  Status:   ❌ TIMEOUT (>10s)")
    except Exception as e:
        print(f"  Status:   ❌ ERROR: {e}")

print(f"\n{'─' * 65}")
print("\nFor your deployment VM, ensure:")
print("  • Outbound HTTPS (port 443) is open for S2 + HN APIs")
print("  • Outbound HTTP  (port 80)  is open for arXiv API")
print("  • No corporate proxy is blocking API requests")
print()
