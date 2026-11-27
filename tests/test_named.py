from pathlib import Path
from analytics.engine import (connect, named_puzzle_names, named_puzzle_ids, named_puzzle_summary,
                              named_puzzle_related, named_puzzle_manifest, puzzle_population_ids,
                              puzzle_matrix, puzzle_related, review_page)
DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_named_sentiment_reconciles():
    with connect(DB) as conn:
        names=named_puzzle_names(conn)
        assert len(names)==9
        summary=named_puzzle_summary(conn)
        assert len(summary)==9
        for row in summary:
            for s in ('positive','negative'):
                ids=named_puzzle_ids(conn,row['tag'],s)
                assert row[s+'_n']==len(ids)
                assert set(ids)<=set(named_puzzle_ids(conn,row['tag']))
                assert row[s+'_pct']==round(100*len(ids)/row['n'],1)
        assert next(x for x in summary if x['tag']=='Temporal calamity puzzle')['positive_n']==85

def test_named_drilldown_and_manifest():
    with connect(DB) as conn:
        tag='Temporal calamity puzzle';s='positive'
        ids=named_puzzle_ids(conn,tag,s)
        m=named_puzzle_manifest(conn,DB,tag,s)
        assert m['population']['review_ids']==ids
        rows=named_puzzle_related(conn,tag,s)
        assert rows
        extra=rows[0]
        subset=named_puzzle_ids(conn,tag,s,related_tag=extra['tag'],related_sentiment=extra['sentiment'])
        assert len(subset)==extra['n']
        page,n=review_page(conn,subset)
        assert n==len(subset)
        assert len(page)<=8
        assert all('assignments' in x for x in page)

def test_positive_first_stage_puzzle_remains_accessible():
    with connect(DB) as conn:
        issue='Puzzle & level design'
        positive=puzzle_population_ids(conn,1,issue,sentiment='positive')
        negative=puzzle_population_ids(conn,1,issue,sentiment='negative')
        assert positive and negative
        assert positive!=negative
        mat={(x['rating'],x['issue']):x['n'] for x in puzzle_matrix(conn,sentiment='positive')}
        assert mat[(1,issue)]==len(positive)
        assert all(x['population_n']==len(positive) for x in puzzle_related(conn,1,issue,sentiment='positive'))
        page,n=review_page(conn,positive)
        assert n==len(positive) and page
