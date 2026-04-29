"""Phase-5 elaboration A/B benchmark.

Compares three paths on the AI-insights elaboration task using the same deep input:
  A) deepseek-v4-pro alone
  B) kimi-k2.6 alone
  C) Combined: deepseek-v4-pro draft -> kimi-k2.6 critic-refine

Runs inside the enrichment-worker container (has DB libs + backend code mounted at /app).

Usage (inside container):
    python /app/scripts/elaboration_benchmark.py --cbes /tmp/cbes.txt \
        --out /tmp/elaboration_results.jsonl

Outputs JSONL: one record per (cbe, path) combination with prompt, output, latency, tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, "/app")

from ai_client import (  # noqa: E402
    _build_corporate_graph,
    _format_staatsblad_events_block,
    _recent_staatsblad_events,
    build_kbo_context_block,
)
from scraper import scrape_company_site  # noqa: E402


DEEPSEEK = os.environ.get("BENCH_DEEPSEEK_MODEL", "deepseek-v4-pro:cloud")
KIMI = os.environ.get("BENCH_KIMI_MODEL", "kimi-k2.6")
ELAB_MAX_TOKENS = 4000
TEMPERATURE = 0.3
SCRAPE_PAGE_TIMEOUT = 12.0
PRESS_TIMEOUT = 8.0
CONCURRENT_COMPANIES = int(os.environ.get("BENCH_CONCURRENCY", "2"))

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "https://ollama.com").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/api/chat"


async def call_ollama(model: str, system: str, prompt: str, max_tokens: int,
                      temperature: float = 0.3, timeout_s: float = 240.0) -> dict:
    """Direct Ollama Cloud call with `think: False` at top level so we get
    actual content instead of chain-of-thought eating the token budget."""
    started = time.monotonic()
    meta = {"text": "", "model": f"ollama:{model}", "input_tokens": 0,
            "output_tokens": 0, "ok": False, "error": None,
            "status_code": None, "latency_ms": 0,
            "done_reason": None, "thinking": ""}
    if not OLLAMA_API_KEY:
        meta["error"] = "no_api_key"
        return meta
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model,
        "stream": False,
        "think": False,  # critical: disables chain-of-thought so content is populated
        "messages": messages,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OLLAMA_CHAT_URL,
                headers={"Authorization": f"Bearer {OLLAMA_API_KEY}",
                         "Content-Type": "application/json"},
                json=payload, timeout=timeout_s,
            )
            meta["status_code"] = resp.status_code
            if resp.status_code == 200:
                data = resp.json()
                msg = data.get("message") or {}
                meta["text"] = (msg.get("content") or "").strip()
                meta["thinking"] = (msg.get("thinking") or "")[:500]
                meta["input_tokens"] = int(data.get("prompt_eval_count") or 0)
                meta["output_tokens"] = int(data.get("eval_count") or 0)
                meta["done_reason"] = data.get("done_reason")
                meta["ok"] = bool(meta["text"])
                if not meta["ok"]:
                    meta["error"] = f"empty_completion (done_reason={meta['done_reason']})"
            else:
                meta["error"] = f"http_{resp.status_code}"
                meta["text"] = resp.text[:300]
    except httpx.TimeoutException:
        meta["error"] = "timeout"
    except Exception as e:
        meta["error"] = f"exc: {e!r}"
    meta["latency_ms"] = int((time.monotonic() - started) * 1000)
    return meta


ELABORATION_SYSTEM_PROMPT = """You write factual narratives for a Belgian private-equity screener. Your job: synthesize what a deal team needs to know about this company in 6-12 minutes of reading.

Rules:
- Be specific: name products, segments, customers when sources support it. Avoid generic phrases ("provides high-quality services").
- Never invent revenue, EBITDA, headcount, or ownership percentages. Quote ranges only when sources state them.
- Distinguish what the company does (offering) from what the company is (legal form, group position).
- For each major claim, append a source tag in square brackets at the end of the sentence: [website], [kbo], [staatsblad], [press], or [group].
- If sources are thin or contradict, say so plainly and set confidence=low.
- Output STRICT JSON matching the schema. No prose around it. No markdown fences.

Schema:
{
  "business_description": "2-3 sentences naming what they actually make/do and primary buyers, with [source] tags.",
  "products_services": ["specific item 1", "specific item 2", "specific item 3"],
  "customer_segments": "Plain-English description of who buys, with [source] tags.",
  "market_position": "Competitive context: niche, scale, geography. With [source] tags.",
  "group_context": "Plain-English description of group structure / ownership. With [source] tags.",
  "history": "1-2 sentences on founding / pivots / key events. Empty string if unknown.",
  "key_management": [{"name": "...", "role": "...", "context": "1-line note"}],
  "source_attribution": {"business_description": ["website"], "products_services": ["website"], "customer_segments": [], "market_position": [], "group_context": [], "history": [], "key_management": []},
  "confidence": "high"
}
Confidence values: "high" | "medium" | "low" | "insufficient_information"."""


REFINE_SYSTEM_PROMPT = """You are a critic-refiner for company narratives. You receive (1) the full source dossier and (2) a draft narrative produced by another model. Your job: identify specific weaknesses and produce an improved version.

Critic checklist:
- Vague phrases that don't tell a deal team anything ("provides quality services", "various sectors", "innovative solutions") -> replace with concrete specifics from the dossier.
- Claims unsupported by the dossier -> remove or downgrade confidence.
- Facts present in the dossier but missing from the draft -> add.
- Inconsistencies between fields (e.g. business_description says distribution, products list manufacturing) -> reconcile.
- Confidence rating mismatched to evidence -> adjust.

Preserve correct content. Do NOT invent new facts not in sources. Output the SAME JSON schema as the draft (no prose, no markdown fences)."""


# Multi-page candidate paths (NL + EN). Probed in order; misses are silently skipped.
MULTI_PAGE_PATHS = [
    "/about", "/about-us", "/over-ons", "/wie-zijn-wij", "/qui-sommes-nous",
    "/products", "/producten", "/services", "/diensten",
    "/team", "/contact",
    "/history", "/onze-geschiedenis", "/notre-histoire",
]


@dataclass
class CompanyInputs:
    cbe: str
    name: str
    city: str | None
    nace_code: str | None
    website_url: str | None
    kbo_block: str
    corporate_graph: dict
    scraped_text: str
    scraped_pages: list[str]
    staatsblad_block: str
    press_block: str

    def deep_input(self) -> str:
        sections = [self.kbo_block]
        if self.staatsblad_block:
            sections.append(self.staatsblad_block)
        if self.press_block:
            sections.append(self.press_block)
        if self.scraped_text:
            sections.append(
                f"<website_corpus pages_fetched=\"{','.join(self.scraped_pages)}\">\n"
                f"{self.scraped_text[:18000]}\n</website_corpus>"
            )
        else:
            sections.append("<website_corpus>(no website content available)</website_corpus>")
        return "\n\n".join(sections)


def fetch_company_row(conn, cbe: str) -> dict | None:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT ci.enterprise_number, ci.name, ci.city, ci.zipcode, ci.nace_code,
               (SELECT value FROM contact c
                  WHERE c.entity_number = ci.enterprise_number AND c.contact_type = 'WEB'
                  LIMIT 1) AS website
          FROM company_info ci
         WHERE ci.enterprise_number = %s
        """,
        (cbe,),
    )
    return cur.fetchone()


def fetch_admin_names(conn, cbe: str) -> list[str]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT name FROM administrator
         WHERE enterprise_number = %s
           AND (mandate_end IS NULL OR mandate_end > CURRENT_DATE)
         LIMIT 5
        """,
        (cbe,),
    )
    return [r[0] for r in cur.fetchall() if r[0]]


def fetch_latest_financials(conn, cbe: str) -> dict | None:
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute(
        """
        SELECT revenue, ebitda, fte_total, fiscal_year
          FROM financial_summary
         WHERE enterprise_number = %s
         ORDER BY fiscal_year DESC NULLS LAST
         LIMIT 1
        """,
        (cbe,),
    )
    return cur.fetchone()


def build_kbo_dict(row: dict, fin: dict | None, graph: dict) -> dict:
    rev = (fin or {}).get("revenue")
    fte = (fin or {}).get("fte_total")
    rev_band = None
    if rev is not None:
        if rev < 1_000_000:
            rev_band = "<EUR 1M"
        elif rev < 10_000_000:
            rev_band = "EUR 1-10M"
        elif rev < 50_000_000:
            rev_band = "EUR 10-50M"
        else:
            rev_band = ">EUR 50M"
    fte_band = None
    if fte is not None:
        if fte < 5:
            fte_band = "<5"
        elif fte < 25:
            fte_band = "5-25"
        elif fte < 100:
            fte_band = "25-100"
        elif fte < 500:
            fte_band = "100-500"
        else:
            fte_band = ">500"
    return {
        "name": row["name"],
        "hq_city": row.get("city"),
        "primary_nace": row.get("nace_code"),
        "revenue_band": rev_band,
        "fte_band": fte_band,
        "majority_shareholders": [
            {"name": s["name"], "ownership_pct": s.get("ownership_pct")}
            for s in graph.get("shareholders", [])[:5]
        ],
        "key_subsidiaries": [
            {"name": s["name"], "country": s.get("country"), "ownership_pct": s.get("ownership_pct")}
            for s in graph.get("subsidiaries", [])[:5]
        ],
        "admins_top3": [a["name"] for a in graph.get("administrators", [])[:3]],
    }


async def multi_page_scrape(base_url: str) -> tuple[str, list[str]]:
    """Scrape homepage + a handful of candidate paths. Concatenate text, dedupe trivially."""
    if not base_url:
        return "", []
    base_url = base_url.strip().rstrip("/")
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    urls = [base_url] + [base_url + p for p in MULTI_PAGE_PATHS]

    seen_text: set[str] = set()
    chunks: list[str] = []
    pages_ok: list[str] = []

    async def _try(u: str) -> tuple[str, str]:
        try:
            text, _src = await asyncio.wait_for(scrape_company_site(u), timeout=SCRAPE_PAGE_TIMEOUT)
            return u, (text or "")
        except Exception:
            return u, ""

    results = await asyncio.gather(*[_try(u) for u in urls])
    for u, text in results:
        if not text or len(text) < 200:
            continue
        head = text[:200]
        if head in seen_text:
            continue
        seen_text.add(head)
        path = u[len(base_url):] or "/"
        chunks.append(f"=== {path} ===\n{text[:4000]}")
        pages_ok.append(path)
    return "\n\n".join(chunks), pages_ok


async def press_search(name: str, city: str | None) -> str:
    """Lightweight DuckDuckGo press lookup. Best-effort; returns empty on failure."""
    if not name:
        return ""
    q = f'"{name}"'
    if city:
        q += f" {city}"
    q += " (overname OR fusie OR investering OR kapitaal OR raise OR acquires OR press)"
    try:
        async with httpx.AsyncClient(timeout=PRESS_TIMEOUT, follow_redirects=True) as client:
            r = await client.get("https://html.duckduckgo.com/html/", params={"q": q})
            if r.status_code != 200:
                return ""
            html = r.text
    except Exception:
        return ""
    snippets = re.findall(
        r'<a class="result__a"[^>]*>([^<]+)</a>.*?<a class="result__snippet"[^>]*>([^<]+)</a>',
        html,
        re.S,
    )
    if not snippets:
        snippets = re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>([^<]+)</a>',
            html,
            re.S,
        )
        snippets = [("", s) for s in snippets]
    items: list[str] = []
    for title, snippet in snippets[:5]:
        title = re.sub(r"\s+", " ", title).strip()
        snippet = re.sub(r"\s+", " ", snippet).strip()
        if not snippet:
            continue
        items.append(f"- {title}: {snippet}" if title else f"- {snippet}")
    if not items:
        return ""
    return "<press_snippets>\n" + "\n".join(items[:5]) + "\n</press_snippets>"


def conn_helpers(conn):
    """Build the (fetch_one, fetch_all) helpers expected by ai_client."""
    def fetch_one(sql, params):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def fetch_all(sql, params):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    return fetch_one, fetch_all


async def gather_inputs(conn, cbe: str) -> CompanyInputs | None:
    row = fetch_company_row(conn, cbe)
    if not row:
        return None
    fin = fetch_latest_financials(conn, cbe)
    _, fetch_all = conn_helpers(conn)
    graph = _build_corporate_graph(fetch_all, cbe)
    kbo_dict = build_kbo_dict(row, fin, graph)
    kbo_block = build_kbo_context_block(kbo_dict)

    website = row.get("website")
    scrape_task = multi_page_scrape(website) if website else _empty_scrape()
    press_task = press_search(row["name"], row.get("city"))
    (scraped_text, pages_ok), press_block = await asyncio.gather(scrape_task, press_task)

    events = _recent_staatsblad_events(fetch_all, cbe, limit=12)
    staatsblad_block = _format_staatsblad_events_block(events) if events else ""

    return CompanyInputs(
        cbe=cbe,
        name=row["name"],
        city=row.get("city"),
        nace_code=row.get("nace_code"),
        website_url=website,
        kbo_block=kbo_block,
        corporate_graph=graph,
        scraped_text=scraped_text,
        scraped_pages=pages_ok,
        staatsblad_block=staatsblad_block,
        press_block=press_block,
    )


async def _empty_scrape():
    return "", []


async def call_model(model: str, system: str, prompt: str) -> dict:
    return await call_ollama(
        model=model, system=system, prompt=prompt,
        max_tokens=ELAB_MAX_TOKENS, temperature=TEMPERATURE,
        timeout_s=240.0,
    )


def parse_json_safely(text: str) -> dict | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None


async def run_one_company(conn, cbe: str) -> list[dict]:
    started = time.monotonic()
    inputs = await gather_inputs(conn, cbe)
    gather_ms = int((time.monotonic() - started) * 1000)
    if not inputs:
        return [{"cbe": cbe, "error": "company_not_found"}]

    deep_input = inputs.deep_input()
    user_prompt = f"Source dossier:\n\n{deep_input}\n\nReturn the JSON object now."

    # A: DeepSeek alone
    a_meta = await call_model(DEEPSEEK, ELABORATION_SYSTEM_PROMPT, user_prompt)
    # B: Kimi alone
    b_meta = await call_model(KIMI, ELABORATION_SYSTEM_PROMPT, user_prompt)

    # C: Combined critic-refine. Reuse A's draft as input to Kimi.
    if a_meta.get("ok"):
        c_prompt = (
            f"Source dossier:\n\n{deep_input}\n\n"
            f"Draft narrative produced by another model:\n\n{a_meta['text']}\n\n"
            f"Critique it and return the refined JSON now."
        )
        c_meta = await call_model(KIMI, REFINE_SYSTEM_PROMPT, c_prompt)
    else:
        c_meta = {"ok": False, "error": "draft_failed", "text": "", "model": KIMI,
                  "input_tokens": 0, "output_tokens": 0, "latency_ms": 0}

    base = {
        "cbe": cbe,
        "name": inputs.name,
        "city": inputs.city,
        "nace_code": inputs.nace_code,
        "website_url": inputs.website_url,
        "scraped_pages": inputs.scraped_pages,
        "input_chars": len(deep_input),
        "input_gather_ms": gather_ms,
    }
    return [
        {**base, "path": "A_deepseek_alone", **a_meta, "parsed": parse_json_safely(a_meta.get("text", ""))},
        {**base, "path": "B_kimi_alone", **b_meta, "parsed": parse_json_safely(b_meta.get("text", ""))},
        {**base, "path": "C_deepseek_then_kimi", **c_meta, "parsed": parse_json_safely(c_meta.get("text", ""))},
    ]


async def run_all(cbes: list[str], out_path: Path) -> None:
    db_url = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(db_url)
    sem = asyncio.Semaphore(CONCURRENT_COMPANIES)

    async def _bound(cbe: str) -> list[dict]:
        async with sem:
            try:
                return await run_one_company(conn, cbe)
            except Exception as e:
                return [{"cbe": cbe, "error": f"runtime: {e!r}"}]

    print(f"[bench] running {len(cbes)} companies, {CONCURRENT_COMPANIES} concurrent", flush=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with out_path.open("w", encoding="utf-8") as fp:
        completed = 0
        for fut in asyncio.as_completed([_bound(c) for c in cbes]):
            records = await fut
            for r in records:
                fp.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                fp.flush()
            completed += 1
            print(f"[bench] {completed}/{len(cbes)} done", flush=True)

    conn.close()
    print(f"[bench] wrote {out_path}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cbes", required=True, help="path to file with one CBE per line")
    ap.add_argument("--out", required=True, help="path to write JSONL results")
    args = ap.parse_args()

    cbes = [
        line.strip()
        for line in Path(args.cbes).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not cbes:
        print("no CBEs in input file", file=sys.stderr)
        return 1
    asyncio.run(run_all(cbes, Path(args.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
