"""Auditable JSON exports for exact evidence selections (no AI dependency)."""
from __future__ import annotations
from .engine import fingerprint, review_page


def evidence_package(conn, db_path, ids, conditions, *, search='', order='recent', language='all'):
    """Export every matching review, not just the current visible page.

    Reviews are unique; assignments are not deduplicated in exported records.
    All stored original spans remain available alongside whether they can be
    highlighted exactly. Translations are deliberately excluded.
    """
    ids=list(dict.fromkeys(ids))
    rows, matched=review_page(conn, ids, page=1, per_page=max(1,len(ids)),
                              search=search, order=order, language=language)
    verified=sum(t['verified'] for r in rows for t in r['assignments'])
    assignments=sum(len(r['assignments']) for r in rows)
    return {
        'schema_version':'1.0',
        'dataset_sha256':fingerprint(db_path),
        'selection':dict(conditions),
        'view_filters':{'search':search,'sort':order,'language':language},
        'counting_unit':'unique reviews matching all selected conditions',
        'matching_review_count':matched,
        'evidence_quality':{'assignments':assignments,'verified_spans':verified,
                            'unverified_spans':assignments-verified},
        'notes':['Original review bodies and every stored tag assignment are included.',
                 'A single review can have different sentiments for the same tag.',
                 'The translated text is never used in calculations or included in this export.',
                 'Co-occurrence does not mean the technical issue took place inside the named puzzle.'],
        'reviews':rows,
    }
