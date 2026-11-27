from pathlib import Path
from analytics.engine import (connect, recommended_sentiment_summary, recommended_sentiment_ids,
                              recommended_related, recommended_manifest, playtime_summary, playtime_ids,
                              playtime_related, playtime_manifest)
DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_both_recommendation_sentiments_are_traceable():
    with connect(DB) as conn:
        distributions={rating:{r['sentiment']:r['n'] for r in recommended_sentiment_summary(conn,rating)} for rating in (1,0)}
        assert distributions[1]=={'positive':484,'negative':46,'mixed':222,'neutral':66}
        assert distributions[0]=={'positive':6,'negative':1182,'mixed':112,'neutral':27}
        for rating in (1,0):
            for sent,n in distributions[rating].items():
                ids=recommended_sentiment_ids(conn,sent,rating=rating)
                assert len(ids)==len(set(ids))==n
                report=recommended_manifest(conn,DB,sent,rating=rating)
                assert report['population']['review_ids']==ids
            rows=recommended_related(conn,'mixed',rating=rating)
            for r in rows:
                assert len(recommended_sentiment_ids(conn,'mixed',r['tag'],r['sentiment'],rating=rating))==r['n']

def test_playtime_buckets_are_exclusive_and_explorable():
    with connect(DB) as conn:
        data=playtime_summary(conn)
        assert sum(x['n'] for x in data)==2145
        assert sum(x['recommended'] for x in data)==818
        assert sum(x['not_recommended'] for x in data)==1327
        assert [(x['bucket'],x['n'],x['recommended']) for x in data if x['bucket'] in ('3–6 hours','6–12 hours')]==[
            ('3–6 hours',308,153),('6–12 hours',520,156)]
        all_ids=[]
        for x in data:
            ids=playtime_ids(conn,x['bucket'])
            assert len(ids)==x['n']==len(set(ids))
            all_ids+=ids
            for rating in (1,0):
                subset=playtime_ids(conn,x['bucket'],rating=rating)
                assert len(subset)==x['recommended' if rating else 'not_recommended']
            rows=playtime_related(conn,x['bucket'],rating=1)
            for row in rows:
                exact=playtime_ids(conn,x['bucket'],1,row['tag'],row['sentiment'])
                assert len(exact)==row['n']
            report=playtime_manifest(conn,DB,x['bucket'])
            assert report['population']['review_ids']==ids
        assert len(all_ids)==len(set(all_ids))
