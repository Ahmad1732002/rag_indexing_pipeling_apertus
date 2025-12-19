#!/usr/bin/env python3
"""
RAG System Evaluation Script (with optional reranking)

Usage:
python evaluate_rag.py \
  --excel questions.xlsx \
  --top-k 100 \
  --use-reranker \
  --rerank-top-k 100
"""

import os
import sys
import argparse
import pandas as pd
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse
from query_elasticsearch import simple_search
from datetime import datetime
import json
import time

from sentence_transformers import CrossEncoder

# Load environment
load_dotenv()


# ----------------------------
# RERANKER
# ----------------------------

class Reranker:
    def __init__(self, model_name="cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.model = CrossEncoder(model_name)

    def rerank(self, query, docs, top_k=100):
        """
        docs: list of ES result dicts, must contain 'text'
        """
        pairs = [(query, d["text"]) for d in docs if d.get("text")]
        scores = self.model.predict(pairs)

        scored_docs = []
        i = 0
        for d in docs:
            if d.get("text"):
                d["rerank_score"] = float(scores[i])
                i += 1
            else:
                d["rerank_score"] = float("-inf")
            scored_docs.append(d)

        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored_docs[:top_k]


# ----------------------------
# URL NORMALIZATION
# ----------------------------

def normalize_url(url):
    if not url or not isinstance(url, str):
        return None

    parsed = urlparse(url.strip())
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        "",
        "",
        ""
    )).lower()

    if normalized.endswith("/"):
        normalized = normalized[:-1]

    for ext in ["/index.html", "/index.htm"]:
        if normalized.endswith(ext):
            normalized = normalized[:-len(ext)]

    for ext in [".html", ".htm", ".pdf", ".md"]:
        if normalized.endswith(ext):
            normalized = normalized[:-len(ext)]

    return normalized


def is_url_match(result_url, expected_url):
    a = normalize_url(result_url)
    b = normalize_url(expected_url)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def filter_ethz_domains(urls):
    out = []
    for u in urls:
        parsed = urlparse(u)
        if parsed.netloc in ("ethz.ch", "www.ethz.ch"):
            out.append(u)
    return out


# ----------------------------
# EVALUATION
# ----------------------------

def evaluate_question(
    question,
    relevant_docs,
    es_config,
    retrieve_top_k,
    use_query_expansion=False,
    reranker=None,
    rerank_top_k=100,
):
    result = {
        "question": question,
        "relevant_docs": relevant_docs,
        "found_docs": [],
        "missing_docs": [],
        "rank_of_first_match": None,
        "all_ranks": [],
        "search_results": [],
        "success": False,
    }

    search_results = simple_search(
        query=question,
        index_name=es_config["index_name"],
        es_url=es_config["es_url"],
        top_k=retrieve_top_k,
        es_user=es_config["es_user"],
        es_password=es_config["es_password"],
        use_query_expansion=use_query_expansion,
        query_expansion_verbose=False,
    )

    # ----------------------------
    # RERANKING (optional)
    # ----------------------------
    if reranker is not None:
        search_results = reranker.rerank(
            question, search_results, top_k=rerank_top_k
        )

    result["search_results"] = search_results

    # ----------------------------
    # MATCHING
    # ----------------------------
    for relevant_url in relevant_docs:
        found = False
        for rank, sr in enumerate(search_results, start=1):
            if (
                is_url_match(sr.get("url"), relevant_url)
                or is_url_match(sr.get("url_preview"), relevant_url)
            ):
                found = True
                result["found_docs"].append(relevant_url)
                result["all_ranks"].append(rank)
                if result["rank_of_first_match"] is None:
                    result["rank_of_first_match"] = rank
                break

        if not found:
            result["missing_docs"].append(relevant_url)

    result["success"] = len(result["found_docs"]) > 0
    return result


def compute_accuracy_at_k(results, k):
    success = 0
    for r in results:
        topk = r["search_results"][:k]
        for rel in r["relevant_docs"]:
            if any(
                is_url_match(sr.get("url"), rel)
                or is_url_match(sr.get("url_preview"), rel)
                for sr in topk
            ):
                success += 1
                break
    return success / len(results) if results else 0


# ----------------------------
# MAIN
# ----------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--excel", required=True)
    parser.add_argument("--top-k", type=int, default=100)
    parser.add_argument("--use-query-expansion", action="store_true")
    parser.add_argument("--use-reranker", action="store_true")
    parser.add_argument("--rerank-top-k", type=int, default=100)
    args = parser.parse_args()

    es_config = {
        "index_name": os.getenv("INDEX_NAME", "ethz_webarchive"),
        "es_url": os.getenv("ES_URL"),
        "es_user": os.getenv("ELASTIC_USERNAME"),
        "es_password": os.getenv("ELASTIC_PASSWORD"),
    }

    df = pd.read_excel(args.excel)
    df.columns = df.columns.str.lower()

    relevant_cols = [c for c in df.columns if "relevant" in c]

    questions = []
    for _, row in df.iterrows():
        q = str(row["question"]).strip()
        docs = [
            str(row[c]).strip()
            for c in relevant_cols
            if not pd.isna(row[c])
        ]
        docs = filter_ethz_domains(docs)
        if docs:
            questions.append((q, docs))

    reranker = Reranker() if args.use_reranker else None

    results = []
    for i, (q, rel) in enumerate(questions, 1):
        print(f"[{i}/{len(questions)}] {q[:80]}")

        r = evaluate_question(
            q,
            rel,
            es_config,
            retrieve_top_k=args.top_k,
            use_query_expansion=args.use_query_expansion,
            reranker=reranker,
            rerank_top_k=args.rerank_top_k,
        )
        results.append(r)

        print("  ✓ SUCCESS" if r["success"] else "  ✗ FAILURE")

    print("\nAccuracy@k:")
    for k in [1, 3, 5, 10, 25, 50, 100]:
        acc = compute_accuracy_at_k(results, k)
        print(f"  k={k:2d}: {acc:.2%}")


if __name__ == "__main__":
    main()
