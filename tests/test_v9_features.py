"""V9 free exploration and named puzzle/technical association regression."""
from pathlib import Path
from analytics.engine import connect
from analytics.playground import all_tags, filter_ids, sentiment_history, technical_named_overlap
from analytics.candidates import CASES

DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'


def test_playground_all_review_default_and_sentiment_filters():
    with connect(DB) as c:
        all_ids=filter_ids(c)
        assert len(all_ids)==2145
        tag='Co-op experience'
        both=filter_ids(c,tag,['positive','negative'])
        pos=filter_ids(c,tag,['positive'])
        neg=filter_ids(c,tag,['negative'])
        assert set(both)==set(pos)|set(neg)
        assert len(both)<=len(pos)+len(neg)
        and_ids=filter_ids(c,tag,['positive'],'Puzzle & level design',['negative'])
        assert set(and_ids).issubset(set(pos))
        assert and_ids


def test_timeline_is_deterministic_and_accounts_for_multisentiment():
    with connect(DB) as c:
        hist=sentiment_history(c,'Co-op experience')
        hist2=sentiment_history(c,'Co-op experience')
        assert hist==hist2
        assert hist and all(r['n_reviews']<=r['n_sentiment_mentions'] for r in hist)
        assert any(r['positive'] for r in hist)
        assert any(r['negative'] for r in hist)
        assert all(abs(sum(r[s+'_share'] for s in ('positive','negative','neutral','mixed'))-100)<.0001 for r in hist)
        weekly=sentiment_history(c,'Co-op experience',grain='week')
        assert sum(r['positive'] for r in weekly)==sum(r['positive'] for r in hist)


def test_technical_named_overlap_is_unique_review_intersection():
    with connect(DB) as c:
        matrix=technical_named_overlap(c)
        assert len(matrix)==len(set(r['puzzle'] for r in matrix))*6
        for cell in matrix:
            assert cell['n']==len(cell['ids'])
            assert cell['n']<=cell['puzzle_negative_n']
            if cell['n']:
                rid=cell['ids'][0]
                tags={r['tag'] for r in c.execute("SELECT tag FROM review_tags WHERE review_id=? AND sentiment='negative'",(rid,))}
                assert cell['puzzle'] in tags and cell['technical'] in tags
        assert any(r['n']>0 for r in matrix if r['technical']=='Progression blockers')


def test_fandom_reclassified():
    assert CASES['fandom']['chapter']==2
