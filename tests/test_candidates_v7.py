from pathlib import Path
from analytics.engine import connect, exact_span
from analytics.candidates import CASES, candidate_ids, candidate_manifest, related, summary, launch_comparison

DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_cases_have_populations():
    with connect(DB) as c:
        for key in CASES:
            ids=candidate_ids(c,key)
            assert len(ids)>0
            assert len(ids)==len(set(ids))
            assert summary(c,key)

def test_removed_uncertainty_is_not_an_active_case():
    assert 'uncertainty' not in CASES

def test_presentation_and_technical_sentiments_are_separated():
    with connect(DB) as c:
        for case,tag in [('presentation','Graphics & art direction'),('technical','Progression blockers')]:
            pos=set(candidate_ids(c,case,tag=tag,sentiment='positive'))
            neg=set(candidate_ids(c,case,tag=tag,sentiment='negative'))
            assert pos and neg
            assert set(candidate_ids(c,case,tag=tag,sentiment='negative',rating=0)).issubset(neg)

def test_launch_dates_and_manifest():
    with connect(DB) as c:
        rows=launch_comparison(c)
        assert [(r['day'],r['n'],r['recommended']) for r in rows]==[('2026-10-20',139,89),('2026-10-25',160,60)]
        for day in ('2026-10-20','2026-10-25'):
            m=candidate_manifest(c,DB,'launch',day=day)
            assert m['population']['n_reviews']==len(m['population']['review_ids'])
            assert m['definition']['day']==day

def test_technical_related_tag_drilldown_is_exact_subset():
    with connect(DB) as c:
        ids=candidate_ids(c,'technical',rating=0,tag='Progression blockers',sentiment='negative')
        rows=related(c,'technical',ids)
        assert rows
        chosen=rows[0]
        subset=candidate_ids(c,'technical',rating=0,tag='Progression blockers',sentiment='negative',related_tag=chosen['tag'],related_sentiment=chosen['sentiment'])
        assert len(subset)==chosen['n']
