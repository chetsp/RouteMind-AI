"""Conservative evidence review. Scores are heuristics, never probabilities."""
from collections import defaultdict
from datetime import datetime, timezone
import json
import re
from app.rag import tokens

STOP = set('a an the is are was were do does did can could will would should what which how why when where who '
           'and or for of in on at to from by with about these this that any all it its their they me tell please '
           'say says stated state specify specified described describe documented documents document policy policies '
           'carrier carriers compare comparison information provide provides available exact requirements requirement'.split())
CAPABILITIES = {'fragile', 'secure', 'refrigerated', 'hazmat'}


def content_terms(query, carrier_names=()):
    # Remove complete names before tokenization so 'Secure' in a brand name
    # does not make an unrelated refund question look cargo-relevant.
    for name in sorted(carrier_names, key=len, reverse=True):
        query = re.sub(r'\b'+re.escape(name)+r'\b', '', query, flags=re.IGNORECASE)
    names = set(t for name in carrier_names for t in tokens(name)) - CAPABILITIES
    return set(tokens(query)) - STOP - names


def assess_evidence(query, candidates, *, reviews=None, carrier_names=(), capabilities=None, as_of=None):
    """Exclude superseded/expired sources, gate relevance, and check reviewed claims.

    Unreviewed prose has unknown freshness. Contradiction checks here cover only
    explicitly reviewed carrier capability claims; a model may flag prose conflicts.
    """
    reviews = reviews or {}
    now = as_of or datetime.now(timezone.utc)
    terms = content_terms(query, carrier_names)
    excluded, groups = [], defaultdict(list)
    def instant(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    for item in candidates:
        item = dict(item)
        meta = reviews.get(item['source_id'], {})
        start = instant(meta.get('effective_from'))
        if start and start > now:
            excluded.append({'source_id': item['source_id'], 'reason': 'not_yet_effective'})
            continue
        item['freshness'] = 'dated' if start or meta.get('effective_until') else 'unknown'
        item['effective_from'] = meta.get('effective_from')
        item['effective_until'] = meta.get('effective_until')
        group = (item.get('carrier_id'), meta.get('logical_id') or item['source_id'])
        groups[group].append(item)
    current = []
    for group in groups.values():
        newest = max(item['version'] for item in group)
        for item in group:
            end = instant(item.get('effective_until'))
            reason = 'superseded' if item['version'] < newest else 'expired' if end and end <= now else None
            if reason:
                excluded.append({'source_id': item['source_id'], 'reason': reason})
            else:
                current.append(item)
    # Preserve the retriever's rank after grouping versions.
    order = {e['source_id']: index for index, e in enumerate(candidates)}
    relevant = []
    for item in sorted(current, key=lambda e: order[e['source_id']]):
        matched = terms & set(tokens(item['text']))
        similarity = item.get('dense_similarity')
        # Learned similarity can rescue paraphrases; hash similarity cannot.
        semantic = (item.get('embedding_backend') in {'minilm', 'sentence-transformers'}
                    and similarity is not None and similarity >= .55)
        if not terms or (not matched and not semantic):
            excluded.append({'source_id': item['source_id'], 'reason': 'below_relevance_gate'})
            continue
        item['matched_terms'] = sorted(matched)
        item['relevance_basis'] = 'term_overlap' if matched else 'semantic_similarity'
        relevant.append(item)
    conflicts = []
    claims = defaultdict(list)
    for item in relevant:
        raw = reviews.get(item['source_id'], {}).get('claims_json') or '{}'
        reviewed = json.loads(raw) if isinstance(raw, str) else raw
        for capability, enabled in reviewed.items():
            if capability not in CAPABILITIES or type(enabled) is not bool or not item.get('carrier_id'):
                continue
            claims[item['carrier_id'], capability].append((item['source_id'], enabled))
    for (carrier, capability), entries in claims.items():
        disagrees = len({enabled for _, enabled in entries}) > 1
        sql_disagrees = capabilities is not None and any(
            enabled != (capability in capabilities.get(carrier, set())) for _, enabled in entries)
        if disagrees or sql_disagrees:
            conflicts.append({'carrier_id': carrier, 'capability': capability,
                              'source_ids': [ident for ident, _ in entries],
                              'reason': 'reviewed_claim_disagrees_with_sql' if sql_disagrees else 'conflicting_reviewed_claims'})
    return {'status': 'conflicting_evidence' if conflicts else 'sufficient_evidence' if relevant else 'insufficient_evidence',
            'evidence': relevant, 'excluded': excluded, 'conflicts': conflicts,
            'query_terms': sorted(terms),
            'freshness_unknown': [e['source_id'] for e in relevant if e['freshness'] == 'unknown'],
            'gate_version': 'term-overlap-or-learned-cosine-0.55-v1',
            'limitations': 'Relevance is heuristic, not answer completeness. Undated sources have unknown freshness. Structured conflict checks cover reviewed capability claims only.'}
