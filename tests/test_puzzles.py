from pathlib import Path
from analytics.engine import connect,puzzle_population_ids,puzzle_matrix,puzzle_related,puzzle_manifest,review_page,available_languages
DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'

def test_puzzle_issue_denominators():
    with connect(DB) as c:
        counts={(x['rating'],x['issue']):x['n'] for x in puzzle_matrix(c)}
        assert counts[(0,'Puzzle & level design')]==736
        assert counts[(0,'Guidance & clarity')]==511
        assert counts[(0,'Difficulty')]==216
        ids=puzzle_population_ids(c,0)
        assert len(ids)==878 and len(ids)==len(set(ids))

def test_puzzle_manifest_and_filter():
    with connect(DB) as c:
        ids=puzzle_population_ids(c,0,'Guidance & clarity')
        info=puzzle_manifest(c,DB,0,'Guidance & clarity')
        assert info['population']['review_ids']==ids
        assert info['population']['n_reviews']==511
        assert info['evidence_quality']['exact_spans']+info['evidence_quality']['unverified_spans']==info['evidence_quality']['total_assignments']
        assert puzzle_related(c,0,'Guidance & clarity')
        options={row['language']:row['n'] for row in available_languages(c)}
        assert options['unknown']>2000
        all_rows,n=review_page(c,ids)
        unknown_rows,unknown_n=review_page(c,ids,language='unknown')
        assert n>=unknown_n and len(all_rows)<=8 and len(unknown_rows)<=8


def test_named_puzzle_positive_and_negative_mentions():
    with connect(DB) as c:
        selected=set(puzzle_population_ids(c,1,'Puzzle & level design'))
        rows=puzzle_related(c,1,'Puzzle & level design')
        assert rows and all({'positive_n','negative_n','positive_pct','negative_pct','population_n'} <= x.keys() for x in rows)
        for entry in rows:
            assert entry['population_n']==len(selected)
            assert entry['total_mentions']==entry['positive_n']+entry['negative_n']
            assert entry['positive_pct']==round(entry['positive_n']/len(selected)*100,1)
            assert entry['negative_pct']==round(entry['negative_n']/len(selected)*100,1)
            for sent in ('positive','negative'):
                actual={r[0] for r in c.execute('SELECT DISTINCT review_id FROM review_tags WHERE tag=? AND sentiment=?',(entry['tag'],sent))} & selected
                assert len(actual)==entry[sent+'_n']
                assert set(puzzle_population_ids(c,1,'Puzzle & level design',related_tag=entry['tag'],related_sentiment=sent))==actual
