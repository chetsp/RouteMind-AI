"""Persistent Chroma retrieval. Hash vectors are an offline baseline, not a learned model."""
import hashlib
import math
import os
import re
from collections import Counter
from pathlib import Path
import chromadb
from app.database import documents, document_reviews


def tokens(text):
    text = text.lower()
    for pattern, replacement in [(r"delicate|breakable|electronics", "fragile"),
        (r"chilled|cold.chain|temperature.controlled", "refrigerated"),
        (r"high.value|sealed|theft", "secure"), (r"hazardous|dangerous.goods", "hazmat")]:
        text = re.sub(pattern, replacement, text)
    return re.findall(r"[a-z0-9]+", text)


def hash_vector(text):
    ts = tokens(text)
    counts = Counter(ts + [a+"_"+b for a,b in zip(ts, ts[1:])])
    vec = [0.0] * 384
    for token, count in counts.items():
        raw = hashlib.sha256(token.encode()).digest()
        vec[int.from_bytes(raw[:4], "big") % len(vec)] += (1 if raw[4] % 2 else -1) * (1+math.log(count))
    norm = math.sqrt(sum(v*v for v in vec)) or 1
    return [v/norm for v in vec]


class Retriever:
    def __init__(self, db):
        self.db = db
        self.docs = db.all(documents)
        self.by_id = {d["id"]: d for d in self.docs}
        self.encoder = None
        self.onnx = None
        model = os.getenv("EMBEDDING_MODEL")
        revision = os.getenv("EMBEDDING_REVISION")
        backend = os.getenv("EMBEDDING_BACKEND", "auto")
        self.requested_backend = backend
        self.warning = None
        if backend not in {"auto", "minilm", "hash", "sentence-transformers"}:
            raise ValueError("Unknown EMBEDDING_BACKEND")
        if backend == "sentence-transformers":
            if not model:
                raise ValueError("Set EMBEDDING_MODEL for sentence-transformers")
            if not revision:
                raise ValueError("Pin EMBEDDING_REVISION when selecting a learned model")
            from sentence_transformers import SentenceTransformer
            self.encoder = SentenceTransformer(model, revision=revision, trust_remote_code=False)
        elif backend in {"auto", "minilm"}:
            from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
            self.onnx = ONNXMiniLM_L6_V2(preferred_providers=["CPUExecutionProvider"])
            # Keep model artifacts within retained application data, with Chroma's
            # built-in SHA256 verification unchanged.
            self.onnx.DOWNLOAD_PATH = Path(os.getenv('MODEL_CACHE_DIR',str(Path(os.getenv("DATA_DIR", ".data")) / "models"))) / "all-MiniLM-L6-v2"
            try:
                self.embed(['cargo handling'])
            except Exception:
                if backend != 'auto': raise
                self.onnx = None
                self.warning = 'Learned MiniLM embeddings could not load. Offline hash vectors are active; semantic retrieval is unavailable. Select minilm for strict startup or check model-download access.'
        self.backend = 'sentence-transformers' if self.encoder else 'minilm' if self.onnx else 'hash'
        self.model_version = (f"{model}@{revision}" if self.encoder else
            "chroma-onnx-all-MiniLM-L6-v2-" + self.onnx._MODEL_SHA256[:12] if self.onnx else "normalized-feature-hash-v1-384")
        path = Path(os.getenv("DATA_DIR", ".data")) / "chroma"
        client = chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))
        name = "evidence-" + hashlib.sha256(self.model_version.encode()).hexdigest()[:12]
        self.collection = client.get_or_create_collection(name, metadata={"hnsw:space": "cosine"})
        fingerprint = hashlib.sha256(repr(self.docs).encode()).hexdigest()
        if (self.collection.metadata or {}).get("corpus_hash") != fingerprint:
            # Stable IDs make repeated startup idempotent; delete stale IDs explicitly.
            old = set(self.collection.get()["ids"]) - set(self.by_id)
            if old:
                self.collection.delete(ids=list(old))
            if self.docs:
                self.collection.upsert(ids=[d["id"] for d in self.docs],
                    documents=[d["text"] for d in self.docs], embeddings=self.embed([d["text"] for d in self.docs]),
                    metadatas=[{"carrier_id": d["carrier_id"] or "", "document_type": d["document_type"], "version": d["version"], "provenance": "synthetic"} for d in self.docs])
            self.collection.modify(metadata={"corpus_hash": fingerprint})
        self.doc_tokens = {d["id"]: Counter(tokens(d["text"])) for d in self.docs}
        self.avg_len = sum(sum(t.values()) for t in self.doc_tokens.values())/max(1,len(self.docs))

    def embed(self, texts):
        if self.encoder:
            return self.encoder.encode(texts, normalize_embeddings=True).tolist()
        if self.onnx:
            return [v.tolist() for v in self.onnx(texts)]
        return [hash_vector(t) for t in texts]

    def bm25(self, query):
        result = []
        for ident, counts in self.doc_tokens.items():
            score = 0
            for word in set(tokens(query)):
                df = sum(word in t for t in self.doc_tokens.values())
                idf = math.log(1 + (len(self.docs)-df+.5)/(df+.5))
                tf = counts[word]
                score += idf*tf*2.5/(tf+1.5*(.25+.75*sum(counts.values())/self.avg_len))
            result.append((ident, score))
        return sorted(result, key=lambda x:(-x[1], x[0]))

    def query(self, query, k=5, mode="hybrid", carrier_ids=None):
        allowed = {d["id"] for d in self.docs if carrier_ids is None or d["carrier_id"] in carrier_ids or d["carrier_id"] is None}
        if not self.docs:
            return []
        result = self.collection.query(query_embeddings=self.embed([query]), n_results=len(self.docs))
        similarities = {ident: 1-float(distance) for ident, distance in zip(result["ids"][0], result["distances"][0])}
        dense = [i for i in result["ids"][0] if i in allowed]
        lexical = [i for i, score in self.bm25(query) if i in allowed and score > 0]
        if mode == "dense":
            ranked = dense
        elif mode == "bm25":
            ranked = lexical
        else:
            scores = Counter()
            for ranking in (dense, lexical):
                for rank, ident in enumerate(ranking, 1):
                    scores[ident] += 1/(60+rank)
            ranked = sorted(scores, key=lambda i:(-scores[i], i))
            if mode == "reranked":
                # Transparent coverage reranker, not a cross-encoder.
                terms = set(tokens(query))
                top = ranked[:15]
                top.sort(key=lambda i: (-len(terms & self.doc_tokens[i].keys())/max(1,len(terms)), -scores[i], i))
                ranked = top + ranked[15:]
        return [{"source_id": i, "text": self.by_id[i]["text"], "carrier_id": self.by_id[i]["carrier_id"],
                 "document_type": self.by_id[i]["document_type"], "version": self.by_id[i]["version"],
                 "provenance": "synthetic", "retrieval_method": mode, "embedding_version": self.model_version,
                 "embedding_backend": self.backend, "dense_similarity": similarities.get(i)}
                for i in ranked[:k]]


    def assess(self, query, candidates):
        from app.evidence import assess_evidence
        _, carriers, _ = self.db.network()
        reviews = {r['source_id']: r for r in self.db.all(document_reviews)}
        return assess_evidence(query, candidates, reviews=reviews,
            carrier_names=[c['name'] for c in carriers.values()],
            capabilities={i: set(c['capabilities']) for i,c in carriers.items()})
