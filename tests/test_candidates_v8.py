"""V8: deterministic populations and evidence for the final two cases."""
from pathlib import Path
from analytics.engine import connect, fingerprint, review_page
from analytics.candidates import CASES, candidate_ids, summary, related, candidate_manifest

DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_final_cases_integrated():
    for key in ('fandom','motion'):
        assert CASES[key]['chapter']==(2 if key=='fandom' else 3)
        with connect(DB) as conn:
            assert summary(conn,key)
            assert candidate_ids(conn,key)

def test_fandom_cross_sentiment_cohort_and_manifest():
    with connect(DB) as conn:
        ids=candidate_ids(conn,'fandom',rating=0,tag='Anticipation & fandom',sentiment='positive')
        crossing=candidate_ids(conn,'fandom',rating=0,tag='Anticipation & fandom',sentiment='positive',related_tag='Series comparison',related_sentiment='negative')
        assert len(ids)==176
        assert len(crossing)==151
        assert set(crossing).issubset(set(ids))
        m=candidate_manifest(conn,DB,'fandom',rating=0,tag='Anticipation & fandom',sentiment='positive',related_tag='Series comparison',related_sentiment='negative')
        assert m['population']['n_reviews']==151
        assert m['population']['review_ids']==crossing
        assert m['dataset_sha256']==fingerprint(DB)
        rows,total=review_page(conn,crossing,page=1,per_page=4)
        assert total==151 and len(rows)==4
        assert all(r['assignments'] and r['body'] for r in rows)

def test_motion_sickness_and_related():
    with connect(DB) as conn:
        rec=candidate_ids(conn,'motion',rating=1,tag='Motion sickness',sentiment='negative')
        nonrec=candidate_ids(conn,'motion',rating=0,tag='Motion sickness',sentiment='negative')
        assert (len(rec),len(nonrec))==(73,186)
        assert len(set(rec)&set(nonrec))==0
        rows=related(conn,'motion',nonrec)
        assert rows
        chosen=rows[0]
        overlap=candidate_ids(conn,'motion',rating=0,tag='Motion sickness',sentiment='negative',related_tag=chosen['tag'],related_sentiment=chosen['sentiment'])
        assert len(overlap)==chosen['n']
        assert set(overlap).issubset(set(nonrec))
        m=candidate_manifest(conn,DB,'motion',rating=1,tag='Motion sickness',sentiment='negative')
        assert m['population']['review_ids']==rec
        assert m['definition']['sentiment']=='negative'
