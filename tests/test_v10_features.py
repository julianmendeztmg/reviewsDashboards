"""V10 evidence exports, chart population integrity and heatmap drilldown data."""
import json
from pathlib import Path
from analytics.engine import connect
from analytics.playground import technical_named_overlap, filter_ids
from analytics.exports import evidence_package

DB=Path(__file__).resolve().parents[1]/'data'/'reviews.db'


def test_export_single_review_preserves_original_body_and_evidence():
    with connect(DB) as conn:
        match=filter_ids(conn,'Co-op experience',['positive'])
        result=evidence_package(conn,DB,match[:1],{'topic':'test','sentiment':'positive'})
    assert result['matching_review_count']==1
    assert result['reviews'][0]['id']==match[0]
    assert result['reviews'][0]['body']
    assert result['reviews'][0]['assignments']
    assert 'verified' in result['reviews'][0]['assignments'][0]
    assert result['evidence_quality']['assignments']==len(result['reviews'][0]['assignments'])
    assert len(result['dataset_sha256'])==64
    json.dumps(result,ensure_ascii=False)


def test_export_respects_search_and_language_and_full_population():
    with connect(DB) as conn:
        matches=filter_ids(conn,'Motion sickness',['negative'])
        result=evidence_package(conn,DB,matches,{'topic':'motion'},search='xnotafoundstringxyz')
        limited=evidence_package(conn,DB,matches[:14],{'topic':'motion'})
    assert result['matching_review_count']==0
    assert result['reviews']==[]
    assert limited['matching_review_count']==14
    assert len(limited['reviews'])==14  # not just first 8


def test_puzzle_technical_cell_exact_evidence_population():
    with connect(DB) as conn:
        cells=technical_named_overlap(conn)
        cell=next(r for r in cells if r['puzzle']=='Plants puzzle' and r['technical']=='Progression blockers')
        matches=filter_ids(conn,cell['puzzle'],['negative'],cell['technical'],['negative'])
        rows=evidence_package(conn,DB,matches,{'topic':'technical-puzzle-overlap','puzzle':cell['puzzle'],'technical':cell['technical']})
    assert cell['n']==31
    assert set(matches)==set(cell['ids'])
    assert rows['matching_review_count']==cell['n']
    for row in rows['reviews']:
        negatives={tag['tag'] for tag in row['assignments'] if tag['sentiment']=='negative'}
        assert {cell['puzzle'],cell['technical']}<=negatives


def test_heatmap_click_has_one_canonical_drawer_callback():
    source=(DB.parents[1]/'app.py').read_text(encoding='utf-8')
    assert "Input('technical-puzzle-overlap','clickData')" in source
    assert "Output('drawer-state','data',allow_duplicate=True)" not in source
    assert "'topic':'technical-puzzle-overlap'" in source
    assert "STAGE_SENTIMENTS=('positive','neutral','mixed','negative')" in source
