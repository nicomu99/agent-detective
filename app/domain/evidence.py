"""The RAG part: search over the case files.

    index = EvidenceIndex.from_dir(Path("case_files"))
    index.search("brandy decanter", k=3)   # -> [{"doc_id", "title", "snippet", "score"}, ...]
    index.get("coroner-report")            # -> {"doc_id", "title", "text"} or None
"""

import re
from pathlib import Path
from collections import Counter

import numpy as np

STOPWORDS = set(
    "a an and are as at be by did do does for from had has have he her his how i if in is it "
    "its me my of on or she so that the their them there they this to was we were what when "
    "where which who will with you your".split()
)


def tokenize(text: str) -> list[str]:
    """Tokenize a string of text into words.

    Takes a string and converts all letters to lowercase. Extracts consecutive
    occurrences of letters and digits. Removes words listed in STOPWORDS, which
    is a set of frequently occurring words that are semantically not meaningful.

    Args:
        text: A string of text.

    Returns:
        A list of tokenized words.
    """
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


class EvidenceIndex:
    """A simple index based on the document "database" that consists of Markdown files."""
    def __init__(self, documents: list[dict]):
        self.documents = documents
        self.document_dict = {doc["doc_id"]: doc for doc in documents}
        self.chunk_list = self.chunk_documents(self.documents)
        self.vocab = {}
        self.idf = None

        text_chunks = [chunk["text"] for chunk in self.chunk_list]
        self._prepare_index(text_chunks)
        self.embeddings = self.embed_texts(text_chunks)

    @staticmethod
    def chunk_documents(documents: list[dict]) -> list[dict]:
        """Chunks a set of documents into paragraphs.

        Assumes the input is a list of dictionaries that have keys doc_id and text.

        Args:
            documents: A list of dictionaries containing the original texts.

        Returns:
            A list of dictionaries containing chunks of text.
        """
        chunk_list = []
        for document in documents:
            paragraphs = document["text"].split("\n\n")
            for idx, paragraph in enumerate(paragraphs):
                if paragraph.startswith("#"):
                    continue
                chunk_list.append({
                    "doc_id": document["doc_id"],
                    "chunk_id": f"{document["doc_id"]}#{idx}",
                    "title": document["title"],
                    "text": paragraph,
                    "tokens": tokenize(document["title"] + " " + paragraph)
                })
        return chunk_list

    def _prepare_index(self, texts: list[str]):
        """Build embeddings from text fragments.

        Computes the inverse document frequency of each word and computes
        embeddings by multiplying the IDF with term frequency per text fragment.

        Args:
            texts: A list of text fragments or chunks.
        """
        word_counter = Counter()
        for sentence in texts:
            tokenized = set(tokenize(sentence))
            word_counter.update(tokenized)

        n = len(texts)
        words = list(sorted(word_counter.keys()))
        self.idf = np.zeros(len(words))
        for idx, word in enumerate(words):
            self.vocab[word] = idx
            self.idf[idx] = np.log((1 + n) / (word_counter[word] + 1)) + 1

    def embed_texts(self, texts: list[str]):
        """Converts a list of texts from characters to TF-IDF vector embeddings.

        Args:
            texts: A list of text fragments for conversion.

        Returns:
            A (n,V) vector of embeddings, where n is the number of texts and V is
            the size of the vocabulary.
        """
        embeddings = np.zeros((len(texts), len(self.vocab)))
        for idx, text in enumerate(texts):
            word_count = Counter(tokenize(text))
            for word, term_frequency in word_count.items():
                if word not in self.vocab:
                    continue
                word_idx = self.vocab[word]
                embeddings[idx, word_idx] = self.idf[word_idx] * term_frequency
        return embeddings

    @classmethod
    def from_dir(cls, case_dir: Path) -> "EvidenceIndex":
        """Load every Markdown file in case_dir

        Args:
            case_dir: Path pointing to the directory containing the case files.

        Returns:
            An instance of EvidenceIndex.
        """
        documents = []
        for path in sorted(Path(case_dir).glob("*.md")):
            text = path.read_text(encoding="utf-8")
            first_line = text.splitlines()[0] if text else path.stem
            documents.append({"doc_id": path.stem, "title": first_line.lstrip("# ").strip(), "text": text})
        if not documents:
            raise FileNotFoundError(f"no case files (*.md) found in {case_dir}")
        return cls(documents)

    def search(self, query: str, k: int = 3) -> list[dict]:
        """Search the `k` most similar chunks to the query.

        Args:
            query: A string of text representing a query.
            k: The number of chunks to retrieve.

        Returns:
            List of dictionaries containing the most similar chunks to the query.
        """
        query_embedding = self.embed_texts([query])[0]

        similarities = self.embeddings @ query_embedding
        sorting = np.argsort(similarities)

        top_k = []
        for idx in sorting:
            score = similarities[idx]
            if score <= 0:
                continue
            chunk = self.chunk_list[idx]

            top_k.append({
                "doc_id": chunk["doc_id"],
                "title": chunk["title"],
                "snippet": chunk["text"],
                "score": score
            })
        return top_k[:k]

    def get(self, doc_id: str) -> dict | None:
        """Get document by document id.

        Retrieve a document by its id. Ignores '.md' file endings.

        Args:
            doc_id: A string document identifier.

        Returns:
            Dictionary with document-related information.
        """
        doc_id = doc_id.replace(".md", "")
        return self.document_dict.get(doc_id, None)
