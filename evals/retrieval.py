"""Step 12: retrieval evals. Does the evidence index find the right case files?

The index returns chunks (paragraphs), so `retrieved` is a list of doc_ids in rank order and can
contain the same doc_id twice, e.g. ["butler-statement", "coroner-report", "butler-statement"].
"""


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    top_k = set(retrieved[:k])
    count = sum(1 for r in relevant if r in top_k)
    return count / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    for idx, r in enumerate(retrieved):
        if r in relevant:
            return 1 / float(idx + 1)
    return 0.0


def evaluate_retrieval(index, cases: list[dict], k: int = 3) -> dict:
    recall, r_rank, total = 0.0, 0.0, 0
    misses = []
    for case in cases:
        relevant = case["relevant_docs"]
        if not relevant:
            continue
        total += 1
        retrieved = index.search(case["question"], k=k)
        retrieved_ids = [r["doc_id"] for r in retrieved]

        case_recall = recall_at_k(retrieved_ids, relevant, k)
        recall += case_recall
        r_rank += reciprocal_rank(retrieved_ids, relevant)
        if case_recall < 1:
            misses.append(case["id"])
    return {f"recall@{k}": recall / total, "mrr": r_rank / total, "misses": misses}
