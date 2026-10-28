"""Retrieval evals."""


def recall_at_k(retrieved: list[str], relevant: list[str], k: int) -> float:
    """Computes the retrieval recall for a given k.

    For a single evaluation instance, computes the recall of how many relevant sources were actually found by the
    RAG system.

    Args:
        retrieved: A list of case file identifiers the RAG system returned for some query, ordered by relevancy.
        relevant: The relevant case files for some query.
        k: The number of sources the RAG system should retrieve.

    Returns:
        The recall at k for a single evaluation instance.
    """
    top_k = set(retrieved[:k])
    count = sum(1 for r in relevant if r in top_k)
    return count / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: list[str]) -> float:
    """Computes the reciprocal rank of the most relevant retrieved source.

    Computes the reciprocal rank 1 / rank of the most relevant source from retrieved.

    Args:
        retrieved: A list of case file identifiers a RAG system returned for some query, ordered by relevancy.
        relevant: List of relevant case files for some query.

    Returns:
        The reciprocal rank of the most relevant retrieved source or 0.0 if no retrieved source is relevant.
    """
    for idx, r in enumerate(retrieved):
        if r in relevant:
            return 1 / float(idx + 1)
    return 0.0


def evaluate_retrieval(index, cases: list[dict], k: int = 3) -> dict:
    """Evaluates the retrieval performance.

    Calculates the mean recall at k and mean reciprocal rank for all evaluation cases. A case with no relevant docs
    is skipped.

    Args:
        index: Search index that is used to retrieve relevant docs.
        cases: A list of evaluation instances. The instances mut contain at least the keys `question` and
            `relevant_docs` to be evaluated.
        k: The number of retrieved documents.

    Returns:
        A dictionary containing the mean recall, mean reciprocal rank and number of cases where no relevant sources
        were found.
    """
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
