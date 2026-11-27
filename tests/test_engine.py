from pathlib import Path
import pytest
from analytics.engine import (connect,baseline,matrix,population_ids,related_comparisons,
    evidence_quality,manifest,review_page,exact_span,fingerprint)

DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

@pytest.fixture
def db():
    with connect(DB) as conn: yield conn

def test_baseline(db):
    b=baseline(db)
    assert (b['n'],b['recommended'],b['not_recommended'],b['coop_unique_reviews'])==(2145,818,1327,679)

def test_matrix(db):
    mapping={(x['rating'],x['sentiment']):x['n'] for x in matrix(db)}
    assert mapping=={(1,'positive'):218,(1,'negative'):46,(1,'mixed'):23,(1,'neutral'):28,
                    (0,'positive'):17,(0,'negative'):272,(0,'mixed'):25,(0,'neutral'):53}

def test_review_membership_and_overlap(db):
    ids=population_ids(db)
    assert len(ids)==679 and len(ids)==len(set(ids))
    assert len(population_ids(db,1,'positive'))==218
    assert len(population_ids(db,0,'negative'))==272
    assert sum(x['n'] for x in matrix(db))>len(ids)

def test_related_combination(db):
    assert len(population_ids(db,1,'positive','Puzzle & level design','positive'))==82
    assert len(population_ids(db,0,'negative','Puzzle & level design','negative'))==234

def test_comparison_excludes_cohort(db):
    rows=related_comparisons(db,1,'positive',limit=50)
    match=next(x for x in rows if x['tag']=='Puzzle & level design' and x['sentiment']=='positive')
    assert (match['n'],match['comparison_n'],match['cohort_n'],match['other_n'])==(82,94,218,600)

def test_evidence_exactness(db):
    assert evidence_quality(db)=={'total_assignments':701,'exact_spans':695,'unverified_spans':6}
    assert exact_span('hello world',0,5,'hello')
    assert not exact_span('hello world',0,5,'HELLO')

def test_manifest_is_derived_and_traceable(db):
    result=manifest(db,DB,1,'positive','Puzzle & level design','positive')
    assert result['population']['n_reviews']==82
    assert len(result['population']['review_ids'])==82
    assert result['dataset_sha256']==fingerprint(DB)
    assert result['definition']['related_tag']=='Puzzle & level design'
    rows,total=review_page(db,result['population']['review_ids'],page=1,per_page=5)
    assert total==82 and len(rows)==5
    assert all('assignments' in r and 'body' in r for r in rows)

def test_search_stays_within_cohort(db):
    ids=population_ids(db,0,'positive')
    rows,total=review_page(db,ids,search='this string is implausible and does not occur in reviews')
    assert total==0 and rows==[]

def test_new_database_review_changes_population(tmp_path):
    """No cohort sizes are hardcoded: adding a review changes calculations."""
    import shutil, sqlite3
    new_db=tmp_path/'updated.db'
    shutil.copy2(DB,new_db)
    write=sqlite3.connect(new_db)
    write.execute("""INSERT INTO reviews (id,original,rating,body,status) VALUES
        ('test-new-review','{}',1,'Great co-op work together','ok')""")
    write.execute("""INSERT INTO review_tags (review_id,tag,sentiment,evidence_quote,span_start,span_end,found)
        VALUES ('test-new-review','Co-op experience','positive','co-op',6,11,1)""")
    write.commit();write.close()
    with connect(new_db) as conn:
        assert baseline(conn)['n']==2146
        assert len(population_ids(conn,1,'positive'))==219
        assert manifest(conn,new_db,1,'positive')['dataset_sha256']!=fingerprint(DB)
