from pathlib import Path
from analytics.engine import (connect, recommended_sentiment_summary, recommended_sentiment_ids,
                              recommended_related, recommended_manifest,puzzle_matrix,named_puzzle_summary)
DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_recommended_distribution_and_linked_review_populations():
    with connect(DB) as c:
        rows={r['sentiment']:r['n'] for r in recommended_sentiment_summary(c)}
        assert rows=={'positive':484,'mixed':222,'negative':46,'neutral':66}
        assert sum(rows.values())==818
        for sentiment,count in rows.items():
            ids=recommended_sentiment_ids(c,sentiment)
            assert len(ids)==count and len(ids)==len(set(ids))

def test_recommended_related_and_manifest():
    with connect(DB) as c:
        mixed=recommended_related(c,'mixed')
        assert any(r['tag']=='Series comparison' and r['sentiment']=='negative' and r['n']==107 for r in mixed)
        for row in mixed:
            ids=recommended_sentiment_ids(c,'mixed',row['tag'],row['sentiment'])
            assert len(ids)==row['n']
        m=recommended_manifest(c,DB,'mixed')
        assert m['population']['n_reviews']==222
        q=m['evidence_quality']
        assert q['total_assignments']==q['exact_spans']+q['unverified_spans']
        assert q['total_assignments']>222

def test_optimized_figures_preserve_counts():
    with connect(DB) as c:
        m={(r['rating'],r['issue']):r['n'] for r in puzzle_matrix(c)}
        assert m[(0,'Puzzle & level design')]==736
        assert m[(0,'Guidance & clarity')]==511
        named={r['tag']:r for r in named_puzzle_summary(c)}
        assert named['Temporal calamity puzzle']['positive_n']==85
        assert named['DNA puzzle']['negative_n']==107
