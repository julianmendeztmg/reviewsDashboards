"""Regression checks for V12 navigation and direct review evidence paths."""
from datetime import date
from pathlib import Path
import ast
from analytics.engine import connect
from analytics.candidates import summary, candidate_ids

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/'data'/'reviews.db'
SOURCE=(ROOT/'app.py').read_text(encoding='utf8')


def extracted(name, globals_):
    tree=ast.parse(SOURCE)
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),'app.py','exec'),globals_)
    return globals_[name]


def test_no_chapters_route_and_daily_evidence_population():
    assert "dcc.Link('All chapters · Report'" not in SOURCE
    assert "html.Div(id='home-page'" not in SOURCE
    with connect(DB) as conn:
        day=conn.execute("SELECT substr(date,1,10) FROM reviews WHERE status='ok' ORDER BY date LIMIT 1").fetchone()[0]
        fn=extracted('ids_for_drawer',{'filter_ids':None,'candidate_ids':None})
        for rating in (0,1):
            found=fn(conn,{'topic':'daily-volume','day':day,'rating':rating})
            expected={r[0] for r in conn.execute("SELECT id FROM reviews WHERE status='ok' AND substr(date,1,10)=? AND rating=?",(day,rating))}
            assert set(found)==expected


def test_launch_uses_live_dataset_dates():
    assert "'2026-11-08'" not in (ROOT/'analytics'/'candidates.py').read_text()
    with connect(DB) as conn:
        rows=summary(conn,'launch')
        assert rows and max(r['day'] for r in rows) <= date.today().isoformat()
        assert len(candidate_ids(conn,'launch'))==sum(r['n'] for r in rows)


def test_playground_is_tag_conditional():
    fn=extracted('show_playground_results',{})
    assert fn(None,None,0)==({'display':'none'},{'display':'none'})
    assert fn('Voice chat',None,0)==({'display':'block'},{'display':'block'})
    assert fn(None,'Voice chat',1)==({'display':'block'},{'display':'block'})
    assert fn(None,'Voice chat',0)==({'display':'none'},{'display':'none'})


def test_page_reset_results_match_declared_outputs():
    tree=ast.parse(SOURCE)
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reset_page_on_navigation')
    scope={'CASES':{'presentation':{},'technical':{},'fandom':{},'motion':{},'launch':{}},
           'STAGE_SENTIMENTS':('positive','negative','neutral','mixed')}
    fn.decorator_list=[]
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'app.py','exec'),scope)
    result=scope['reset_page_on_navigation']('/named-puzzles')
    assert len(result)==5+len(scope['CASES'])+17+6+len(scope['CASES'])
    assert result[5+len(scope['CASES'])]=={'open':False}
    assert all(v is None for v in result[:5+len(scope['CASES'])])
