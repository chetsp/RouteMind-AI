"""Read-only browsing of reference data and the active evidence index."""
import json
import math
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import String, cast, func, or_, select
from app.database import hubs, carriers, capabilities, schedules, documents

router = APIRouter(prefix="/api/v1/explorer", tags=["Data explorer"])
TABLES = {"hubs": hubs, "carriers": carriers, "capabilities": capabilities,
          "schedules": schedules, "documents": documents}


@router.get("")
def overview(request: Request):
    retriever = request.app.state.retriever
    with request.app.state.db.engine.connect() as conn:
        counts = {name: conn.scalar(select(func.count()).select_from(table))
                  for name, table in TABLES.items()}
    return {"read_only": True, "data_type": "synthetic", "tables": counts,
            "vectors": retriever.collection.count(), "collection": retriever.collection.name,
            "embedding_model": retriever.model_version, "embedding_backend": retriever.backend,
            "warning": retriever.warning}


@router.get("/tables/{name}")
def table_rows(name: str, request: Request, q: str = Query("", max_length=200),
               limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    table = TABLES.get(name)
    if table is None:
        raise HTTPException(404, "Reference dataset not found")
    query = select(table)
    if q.strip():
        # Bound values and escaped LIKE wildcards: user input is always literal text.
        query = query.where(or_(*(cast(c, String).icontains(q.strip(), autoescape=True)
                                 for c in table.columns)))
    with request.app.state.db.engine.connect() as conn:
        total = conn.scalar(select(func.count()).select_from(query.subquery()))
        rows = [dict(r) for r in conn.execute(query.order_by(*table.primary_key.columns)
                                            .limit(limit).offset(offset)).mappings()]
    if name == "hubs":
        for row in rows:
            row["aliases"] = json.loads(row["aliases"])
    return {"columns": list(table.columns.keys()), "rows": rows,
            "total": total, "limit": limit, "offset": offset}


@router.get("/vectors")
def vectors(request: Request, q: str = Query("", max_length=200),
            limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    # Read the actual active Chroma collection, including its persisted metadata/text.
    result = request.app.state.retriever.collection.get(include=["documents", "metadatas"])
    rows = [{"source_id": ident, "text": result["documents"][i],
             **(result["metadatas"][i] or {})} for i, ident in enumerate(result["ids"])]
    needle = q.strip().casefold()
    rows = sorted((r for r in rows if needle in json.dumps(r).casefold()), key=lambda r: r["source_id"])
    return {"columns": ["source_id", "carrier_id", "document_type", "version", "provenance", "text"],
            "rows": rows[offset:offset+limit], "total": len(rows), "limit": limit, "offset": offset}


@router.get("/vectors/{source_id}")
def vector_detail(source_id: str, request: Request):
    result = request.app.state.retriever.collection.get(ids=[source_id],
                                                       include=["documents", "metadatas", "embeddings"])
    if not result["ids"]:
        raise HTTPException(404, "Vector not found in active collection")
    vector = result["embeddings"][0].tolist()
    return {"source_id": source_id, "text": result["documents"][0],
            "metadata": result["metadatas"][0], "dimension": len(vector),
            "norm": math.sqrt(sum(v*v for v in vector)), "embedding": vector}
