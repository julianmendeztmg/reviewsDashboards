"""Regression checks for V11 report simplification and review volume chart."""
import ast
from pathlib import Path
import plotly.graph_objects as go
from analytics.engine import connect, PUZZLE_ISSUES, named_puzzle_names, puzzle_population_ids, puzzle_related, named_puzzle_ids
from analytics.candidates import CASES, summary

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'reviews.db'

def figure_functions():
    source=ast.parse((ROOT/'app.py').read_text())
    scope={'go':go, 'connection':lambda:connect(DB), 'PUZZLE_ISSUES':PUZZLE_ISSUES,
           'named_puzzle_names':named_puzzle_names, 'COLOURS':{'positive':'#279d7a','negative':'#dc7970'},
           'CASES':CASES, 'candidate_summary':summary,
           'PATCH_EVENTS':(('2026-10-23','Patch 1.1.2'),('2026-10-30','Patch 1.1.3'),
                           ('2026-11-09','Patch 1.2'),('2026-11-19','Hotfix 1.2.1'))}
    for node in source.body:
        if isinstance(node,ast.FunctionDef) and node.name in ('make_puzzle_figure','make_named_figure','candidate_figure','review_volume_figure'):
            exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),scope)
    return scope

def test_removed_uncertainty_and_positive_negative_charts():
    assert 'uncertainty' not in CASES
    f=figure_functions()
    for name,params in [('make_puzzle_figure',()),('make_named_figure',()),('candidate_figure',('presentation',)),('candidate_figure',('fandom',))]:
        fig=f[name](*params)
        assert len(fig.data)==2
        assert [tr.name for tr in fig.data]==['Positive','Negative']
        assert fig.layout.barmode=='group'

def test_chart_click_populations_include_both_recommendation_groups():
    with connect(DB) as conn:
        all_r=puzzle_population_ids(conn,None,'Puzzle & level design',sentiment='positive')
        assert len(all_r)>0
        assert set(all_r)==set(puzzle_population_ids(conn,0,'Puzzle & level design',sentiment='positive')) | set(puzzle_population_ids(conn,1,'Puzzle & level design',sentiment='positive'))
        assert puzzle_related(conn,None,'Puzzle & level design',sentiment='positive')
        assert named_puzzle_ids(conn,'Temporal calamity puzzle','positive',None)

def test_volume_chart_review_counts_and_patch_markers():
    chart=figure_functions()['review_volume_figure']()
    assert len(chart.data)==2
    assert all(value>=0 for value in chart.data[0].y)
    assert all(value<=0 for value in chart.data[1].y)
    assert sum(chart.data[0].y)==818
    assert sum(-n for n in chart.data[1].y)==1327
    assert len(chart.layout.shapes)==4
    assert len(chart.layout.annotations)==4
    assert chart.layout.xaxis.range[1] >= '2026-11-19'
