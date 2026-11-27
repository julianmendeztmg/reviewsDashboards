"""Review Intelligence / Co-op vertical slice.
Run: python app.py  (after pip install -r requirements.txt)
"""
from __future__ import annotations
import json
import os
import re
from pathlib import Path

import dash
from dash import Dash, Input, Output, State, dcc, html, ctx, no_update
import plotly.graph_objects as go
from analytics.playground import all_tags, filter_ids, sentiment_history, technical_named_overlap
from analytics.translation import translate_review_body
from analytics.candidates import CASES, candidate_ids, summary as candidate_summary, related as candidate_related, candidate_manifest, launch_comparison
from analytics.engine import (connect, baseline, matrix, population_ids, related_comparisons,
                              review_page, evidence_quality, manifest, fingerprint, available_languages,
                              PUZZLE_ISSUES, puzzle_matrix, puzzle_population_ids, puzzle_related,
                              puzzle_manifest, evidence_quality_for_tags, named_puzzle_names, named_puzzle_ids,
                              named_puzzle_summary, named_puzzle_related, named_puzzle_manifest,
                              recommended_sentiment_summary, recommended_sentiment_ids, recommended_related, recommended_manifest,
                              playtime_summary, playtime_ids, playtime_related, playtime_manifest)

ROOT=Path(__file__).resolve().parent
DB=Path(os.environ.get('REVIEWS_DB', str(ROOT/'data'/'reviews.db'))).expanduser().resolve()
INTERPRETATIONS=ROOT/'interpretations'/'coop.json'
SEMANTIC_AUDIT=ROOT/'interpretations'/'coop_semantic_audit.json'
PUZZLE_INTERPRETATIONS=ROOT/'interpretations'/'puzzles.json'
NAMED_INTERPRETATIONS=ROOT/'interpretations'/'named_puzzles.json'
UNEXPECTED_INTERPRETATIONS=ROOT/'interpretations'/'mixed_recommendations.json'
PLAYTIME_INTERPRETATIONS=ROOT/'interpretations'/'playtime.json'
SEMANTIC_FLAGS={row['review_id']:row for row in json.load(open(SEMANTIC_AUDIT,encoding='utf-8'))['records']}
COLOURS={'positive':'#279d7a','negative':'#dc7970','mixed':'#dab45d','neutral':'#8da0b4'}
# Recommendation is encoded by hue family; individual tag sentiment by tint/pattern.
STAGE_SENTIMENTS=('positive','neutral','mixed','negative')
# Stack within each recommendation family in a stable reading order.
# Both recommendation families share one axis position per tag; the complete
# bar represents sentiment-specific review mentions, not always unique reviews.
STAGE_RATINGS=(0,1)  # non-recommended (red), then recommended (green)
STAGE_PALETTE={
 (1,'positive'):'#95dbc2',(1,'negative'):'#176c59',
 (1,'neutral'):'#668f87',(1,'mixed'):'#87948a',
 (0,'positive'):'#f2a49e',(0,'negative'):'#a53a46',
 (0,'neutral'):'#a68489',(0,'mixed'):'#bd8d92'}

def stage_marker(rating,sent):
    d={'color':STAGE_PALETTE[(rating,sent)],'line':{'width':.6,'color':'#182935'}}
    if sent=='mixed':d['pattern']={'shape':'/','fgcolor':'#fff','fgopacity':.7,'size':7,'solidity':.23}
    return d



def load_playtime_interpretations():
    return json.loads(PLAYTIME_INTERPRETATIONS.read_text(encoding="utf-8"))

def load_unexpected_interpretations():
    return json.loads(UNEXPECTED_INTERPRETATIONS.read_text(encoding="utf-8"))


def load_named_interpretations():
    return json.loads(NAMED_INTERPRETATIONS.read_text(encoding='utf-8'))

def load_puzzle_interpretations():
    with open(PUZZLE_INTERPRETATIONS,encoding='utf-8') as f:return json.load(f)

def load_interpretations():
    with open(INTERPRETATIONS,encoding='utf-8') as f: return json.load(f)


def connection(): return connect(DB)

def language_options():
    with connection() as conn: return available_languages(conn)


def pill(text, tone='muted'):return html.Span(text,className='pill '+tone)


def block_title(kicker,title,desc=None):
    return html.Div([html.Div(kicker,className='eyebrow'),html.H2(title),
        html.P(desc,className='subtle') if desc else None],className='section-head')


def make_matrix_figure():
    with connection() as conn: rows=matrix(conn)
    lookup={(r['rating'],r['sentiment']):r for r in rows}
    fig=go.Figure()
    for rating,label in ((1,'Recommended'),(0,'Not recommended')):
        for sent in STAGE_SENTIMENTS:
            r=lookup.get((rating,sent))
            if not r:continue
            fig.add_trace(go.Bar(name=label+' · '+sent.capitalize(),x=[label],y=[r['n']],
                marker=stage_marker(rating,sent),
                customdata=[[rating,sent,r['denominator'],r['percentage']]],
                text=[str(r['n'])],textposition='inside',
                hovertemplate='%{x}<br>'+sent.capitalize()+': %{y} reviews<br>%{customdata[3]}% of recommendation group<extra></extra>'))
    fig.update_layout(barmode='stack',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed','family':'Inter,Arial'},legend={'orientation':'h','y':1.35,'font':{'size':10}},
        margin={'l':20,'r':10,'t':85,'b':10},height=395,yaxis={'title':'Sentiment-specific review mentions','gridcolor':'#243444'})
    return fig


def make_related_figure(rows):
    rows=rows[:12]
    fig=go.Figure()
    for sent in ('positive','negative'):
        entries=[r for r in reversed(rows) if r['sentiment']==sent]
        fig.add_trace(go.Bar(name=sent.capitalize(),orientation='h',
            y=[r['tag']+' · '+r['sentiment'] for r in entries],x=[r['difference'] for r in entries],
            customdata=[[r['tag'],r['sentiment'],r['n'],r['pct'],r['other_pct']] for r in entries],
            marker_color=COLOURS[sent],
            hovertemplate='<b>%{customdata[0]} / %{customdata[1]}</b><br>%{customdata[2]} in selected cohort<br>%{customdata[3]}% in cohort vs %{customdata[4]}% in peers<br>Difference: %{x:+.1f} percentage points<extra></extra>'))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed','family':'Inter,Arial'},
        barmode='relative',height=455,margin={'l':215,'r':20,'t':12,'b':35},
        legend={'orientation':'h','y':1.12},
        xaxis={'title':'Percentage-point difference vs other reviews with same recommendation','zerolinecolor':'#708399','gridcolor':'#243444'},
        yaxis={'title':'','automargin':True})
    return fig


def highlight_body(body,assignments,review_id,scope="drawer"):
    """Verified evidence ranges have sentiment colors and per-assignment scroll anchors."""
    body=body or ''
    valid=[t for t in assignments if t.get('verified') and t.get('span_start') is not None]
    bounds={0,len(body)}
    for t in valid:bounds.update((t['span_start'],t['span_end']))
    edges=sorted(bounds);nodes=[];anchored=set()
    for a,b in zip(edges,edges[1:]):
        active=[t for t in valid if t['span_start']<=a and t['span_end']>=b]
        segment=body[a:b]
        if active:
            for t in active:
                if t['row_id'] not in anchored:
                    nodes.append(html.Span(id=f'evidence-span-{scope}-{review_id}-{t["row_id"]}',className='evidence-anchor'))
                    anchored.add(t['row_id'])
            tooltip='\n'.join(f"{t['tag']} · {t['sentiment']} — {t.get('reason') or ''}" for t in active)
            sentiment= 'negative' if any(t['sentiment']=='negative' for t in active) else ('positive' if any(t['sentiment']=='positive' for t in active) else ('mixed' if any(t['sentiment']=='mixed' for t in active) else 'neutral'))
            nodes.append(html.Mark(segment,title=tooltip,className='highlight sentiment-'+sentiment))
        else:nodes.append(segment)
    return nodes


def review_card(row,scope="drawer"):
    tags=row['assignments']; unverified=[t for t in tags if not t['verified']]
    audit=SEMANTIC_FLAGS.get(str(row['id']))
    chips=[]
    for t in tags:
        label=f"{t['tag']} · {t['sentiment']}"
        css='tag sentiment-'+str(t['sentiment'])+(' unverified' if not t['verified'] else '')
        chips.append(html.Button(label,title=(t.get('reason') or '') + (' · Click to jump to evidence' if t['verified'] else ' · Unverified span, no jump available'),
                    className=css,id={'type':'evidence-chip','review':str(row['id']),'assignment':str(t['row_id']),'scope':scope},
                    disabled=not t['verified'],n_clicks=0))
    return html.Details([
      html.Summary([
        html.Span('Recommended' if row['rating']==1 else 'Not recommended',className=('review-rating up' if row['rating']==1 else 'review-rating down')),
        html.Strong('Review '+str(row['id'])),
        html.Span((row.get('date') or '')[:10],className='subtle'),
        html.Span(f"{len(tags)} tag assignments",className='subtle')],className='review-summary'),
      html.Div([
        html.Div([pill('Audit: '+audit['label'].replace('_',' '),'warn'),html.Span(audit['audit_note'],className='small subtle')] ,className='pill-row') if audit else None,
        html.P([html.Span('Overall text sentiment: ',className='subtle'),row.get('overall_sentiment') or 'unknown',
                html.Span('  ·  Playtime: ',className='subtle'),str(round((row['playtime_at_review_min'] or 0)/60,1))+'h'],className='meta-line'),
        html.Pre(highlight_body(row['body'],tags,row['id'],scope=scope),className='review-text'),
        html.Div([html.Button('Translate review to English',id={'type':'translate-button','review':str(row['id']),'scope':scope},className='ghost-btn',n_clicks=0),
                  dcc.Loading(html.Div(id={'type':'review-translation','review':str(row['id']),'scope':scope}),type='circle')],className='translation-actions'),
        html.Div(chips,className='tags'),
        html.Button('Export this review (.json)',className='ghost-btn review-export',n_clicks=0,
                    id={'type':'review-json-export','review':str(row['id']),'scope':scope}),
        html.Details([html.Summary('Inspect individual evidence assignments'),html.Div([
          html.Div([html.B(f"{t['tag']} / {t['sentiment']}"),
              html.P('Quote: '+str(t.get('evidence_quote') or ''),className='small'),
              html.P('Reason: '+str(t.get('reason') or ''),className='small'),
              pill('Exact span' if t['verified'] else 'Unverified span', 'good' if t['verified'] else 'warn')],className='assignment') for t in tags])]),
        pill(f"{len(unverified)} unverified highlight(s)",'warn') if unverified else None,
        html.A('Open original Steam review ↗',href=row['source_url'],target='_blank',rel='noopener noreferrer',className='source-link') if row.get('source_url') else None,
      ],className='review-detail')
    ],className='review-card')


def case_link(title,summary,href):
    return html.Div([html.H3(title),html.P(summary,className='subtle'),dcc.Link('Explore finding →',href=href,className='cta')],className='panel overview-case')


def chapter_section(number,label,summary,cases):
    return html.Section([html.Div([html.Span('CHAPTER '+str(number),className='eyebrow'),
                 html.H2(label),html.P(summary,className='subtle')],className='chapter-heading'),
                 html.Div(cases,className='chapter-cases')],className='overview-chapter')


def build_home():
    with connection() as conn:data=baseline(conn)
    return html.Div([
      block_title('REVIEW INTELLIGENCE · EXPLORABLE FINDINGS','Explore what players experienced',
        'Three chapters. Each finding moves from measured patterns to interpretation and the original reviews.'),
      html.Div([html.Div([html.Span('Analyzed reviews',className='metric-label'),html.Strong(f"{data['n']:,}")],className='metric'),
        html.Div([html.Span('Recommended',className='metric-label'),html.Strong(f"{data['recommended']:,}")],className='metric'),
        html.Div([html.Span('Co-op reviews',className='metric-label'),html.Strong(f"{data['coop_unique_reviews']:,}")],className='metric')],className='metrics'),
      html.Div([html.H3('Explore the data yourself'),html.P('Filter tags and sentiments, compare overlaps, explore changes over time, and inspect the original reviews.'),dcc.Link('Open Playground →',href='/playground',className='cta')],className='panel'),
      chapter_section(1,'What went well','Which parts of the experience are worth understanding and preserving?',[
        case_link('What makes co-op genuinely satisfying?',
          'Players who appreciate cooperation frequently also praise puzzles and difficulty. Compare four sentiment/recommendation groups.','/coop'),
        case_link('Which named puzzles receive the most praise?',
          'Compare positive and negative mentions for each named puzzle and inspect the original reviews.','/named-puzzles'),
        case_link(CASES['presentation']['title'],CASES['presentation']['description'],'/presentation')]),
      chapter_section(2,'What went wrong','Where does frustration occur, and which experiences overlap?',[
        case_link('Is puzzle frustration about design, clarity, or difficulty?',
          'Compare positive and negative mentions across all reviews, then zoom into named puzzles.','/puzzles'),
        case_link(CASES['technical']['title'],CASES['technical']['description'],'/technical'),
        case_link(CASES['fandom']['title'],CASES['fandom']['description'],'/fandom')]),
      chapter_section(3,'Unexpected findings','What does the recommendation score miss?',[
        case_link('What does review sentiment reveal beyond the recommendation?',
          'Compare positive, mixed, and negative sentiment within both recommendation groups, then inspect individual tags.','/mixed-recommendations'),
        case_link('Why does recommendation vary with playtime?',
          'Compare recommendation rates across playtime groups, then inspect the positive and negative topics in each.','/playtime'),
        case_link(CASES['launch']['title'],CASES['launch']['description'],'/launch'),
        case_link(CASES['motion']['title'],CASES['motion']['description'],'/motion')]),
      html.P('Counts are deterministic; narrative interpretations are maintained separately and may require review after the dataset changes.',className='footnote')
    ],className='page-content')


def build_coop():
    interp=load_interpretations()
    current=fingerprint(DB)
    fresh=current==interp.get('source_dataset_sha256')
    cards=[]
    for i,record in enumerate(interp['interpretations']):
        cards.append(html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs revalidation','good' if fresh else 'warn')],className='pill-row'),
          html.H3(record['title']),html.P(record['claim']),
          html.P([html.B('Basis: '),record['basis']],className='small'),
          
          html.Button('Inspect evidence →',id=f'insight-evidence-{i}',className='ghost-btn')],className='panel insight'))
    return html.Div([
      block_title('CHAPTER 1 · WHAT WENT RIGHT','What makes cooperation satisfying?',
        'Two recommendation bars, each showing positive, negative, neutral and mixed co-op sentiment. Every segment opens its exact review population.'),
      html.Div([pill('Calculated from SQLite','good'),pill('Interpretation stored separately','info')],className='pill-row'),
      html.Div([html.Div([html.H3('1. The distribution'),
          html.P('Select a segment in the stacked chart, or choose the cohort below.',className='subtle'),
          dcc.Graph(id='matrix-graph',figure=make_matrix_figure(),config={'displayModeBar':False}),
          html.Div([html.Div([html.Label('Recommendation'),dcc.Dropdown(id='rating-select',options=[{'label':'Recommended','value':1},{'label':'Not recommended','value':0}],value=None,placeholder='Select a recommendation',clearable=True)],className='filter'),
          html.Div([html.Label('Co-op tag sentiment'),dcc.Dropdown(id='sentiment-select',options=[{'label':x.capitalize(),'value':x} for x in ('positive','negative','mixed','neutral')],value=None,placeholder='Select sentiment',clearable=True)],className='filter')],className='two-cols'),
          html.Button('Clear selection',id='coop-clear',className='ghost-btn'),
          dcc.Loading(html.Div(id='selected-summary'),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'}),
          html.Button('Explore all reviews in this group →',id='inspect-cohort',className='cta button',disabled=True)],className='panel'),
        html.Div([html.H3('2. What else do these players praise or criticize?'),
          html.P('Co-tags are separated by their OWN sentiment. Values compare the selected cohort against other reviews with the same recommendation.',className='subtle'),
          html.Div([html.Label('Rank related tags by'),dcc.Dropdown(id='sort-select',options=[{'label':'Difference in percentage points','value':'difference'},{'label':'Most common','value':'count'},{'label':'Relative prevalence','value':'relative'}],value='difference',clearable=False)],className='filter'),
          dcc.Loading(html.Div([html.Div(id='related-placeholder',children='Select a segment in the distribution to see its related tags.',className='subtle'),
          dcc.Graph(id='related-graph',config={'displayModeBar':False},style={'display':'none'})]),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'}),
          html.P('Click a bar to inspect reviews containing BOTH the selected co-op sentiment and the related tag sentiment.',className='hint')],className='panel')],className='stacked-panels'),
      block_title('STEP 3 · INTERPRETATIONS','What might these patterns mean?',
        'These narrative statements are not statistical calculations. They are independently versioned, qualified interpretations.'),
      html.Div(cards,className='two-cols'),
      html.Div([html.H3('4. The evidence manifest is inside the dashboard'),
          html.P('Open the Evidence workspace to review all matching IDs, query conditions, and validity of quote locations. Download the current manifest if you need a reproducible snapshot.'),
          dcc.Link('Open the evidence workspace →',href='/manifest',className='cta')],className='panel')
    ],className='page-content')


def make_puzzle_figure():
    """Simple positive/negative sentiment comparison, across all recommendations."""
    with connection() as conn:
        rows=conn.execute("""SELECT t.tag,t.sentiment,COUNT(DISTINCT r.id) n FROM review_tags t
             JOIN reviews r ON r.id=t.review_id WHERE r.status='ok'
             AND t.tag IN (?,?,?) AND t.sentiment IN ('positive','negative')
             GROUP BY t.tag,t.sentiment""",list(PUZZLE_ISSUES)).fetchall()
    counts={(r['tag'],r['sentiment']):r['n'] for r in rows}
    fig=go.Figure()
    for sent in ('positive','negative'):
        fig.add_trace(go.Bar(name=sent.capitalize(),x=list(PUZZLE_ISSUES),
            y=[counts.get((tag,sent),0) for tag in PUZZLE_ISSUES],
            marker_color=COLOURS[sent],
            customdata=[[-1,tag,sent,counts.get((tag,sent),0)] for tag in PUZZLE_ISSUES],
            text=[str(counts.get((tag,sent),0)) for tag in PUZZLE_ISSUES],textposition='auto',
            hovertemplate='%{x}<br>'+sent.capitalize()+': %{y} unique reviews<extra></extra>'))
    fig.update_layout(barmode='group',height=445,paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',font={'color':'#d6e2ed'},
        margin={'l':50,'r':15,'t':48,'b':75},
        legend={'orientation':'h','y':1.13},yaxis={'title':'Unique reviews mentioning the tag','gridcolor':'#243444'})
    return fig


def make_puzzle_related(rows):
    """Positive and negative mentions in the selected population (unique reviews per sentiment)."""
    rows=list(reversed(rows))
    fig=go.Figure()
    for sent in ('positive','negative'):
        fig.add_trace(go.Bar(
            name=sent.capitalize(),orientation='h',
            x=[r[sent+'_pct'] for r in rows],y=[r['tag'] for r in rows],
            marker_color=COLOURS[sent],
            customdata=[[r['tag'],sent,r[sent+'_n'],r['population_n'],r['positive_n'],r['negative_n']] for r in rows],
            hovertemplate='<b>%{y} · '+sent.capitalize()+'</b><br>%{customdata[2]} / %{customdata[3]} selected reviews (%{x:.1f}%)<br>Positive: %{customdata[4]} · Negative: %{customdata[5]}<extra></extra>'
        ))
    fig.update_layout(barmode='stack',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},height=460,margin={'l':185,'r':20,'t':34,'b':38},
        legend={'orientation':'h','y':1.13},
        xaxis={'title':'% of selected reviews (positive + negative mentions)','gridcolor':'#243444'},
        yaxis={'automargin':True})
    return fig


def build_puzzles():
    interp=load_puzzle_interpretations()
    fresh=fingerprint(DB)==interp.get('source_dataset_sha256')
    with connection() as conn:
        all_issues=len(puzzle_population_ids(conn))
        bad=len(puzzle_population_ids(conn,0))
    return html.Div([
        block_title('CHAPTER 2 · WHAT WENT WRONG','Is puzzle frustration about design, unclear guidance, or difficulty?',
            'Compare distinct complaints and inspect which named puzzles appear in reviews describing those issues.'),
        html.Div([pill(f'{all_issues:,} reviews mention at least one issue','info'),
                  pill(f'{bad:,} are not recommended','muted')],className='pill-row'),
        html.Div([html.Div([html.H3('1. Where does frustration appear?'),
            html.P('Positive (green) and negative (red) mentions of each issue across all reviews. Click either bar to inspect the corresponding reviews.',className='subtle'),
            dcc.Graph(id='puzzle-graph',figure=make_puzzle_figure(),config={'displayModeBar':False}),
            html.Button('Clear selection',id='puzzle-clear',className='ghost-btn'),
            dcc.Loading(html.Div(id='puzzle-selected-summary',className='selection-summary'),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'}),
            html.Button('Explore matching reviews →',id='puzzle-inspect',className='cta button',disabled=True)],className='panel'),
          html.Div([html.H3('2. Which named puzzles appear alongside these complaints?'),
            html.P('Positive (green) and negative (red) sentiment for each named puzzle, as a share of selected reviews. Click a segment to see its exact reviews. A review may have both sentiments.',className='subtle'),
            dcc.Loading(html.Div([html.Div(id='puzzle-related-placeholder',children='Select an issue bar to compare named puzzles.',className='subtle'),
            dcc.Graph(id='puzzle-related',config={'displayModeBar':False},style={'display':'none'})]),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'})],className='panel')],className='stacked-panels'),
        block_title('STEP 3 · INTERPRETATION','What might explain these patterns?',
            'The calculated findings and editorial reading are kept separate.'),
        html.Div([html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs revalidation','good' if fresh else 'warn')],className='pill-row'),
            html.H3(x['title']),html.P(x['claim']),html.P([html.B('Basis: '),x['basis']],className='small'),
            html.Button('Inspect supporting population →',id='puzzle-insight-'+str(i),className='ghost-btn')],className='panel insight')
            for i,x in enumerate(interp['interpretations'])],className='two-cols'),
        html.Div([html.H3('4. Evidence manifest'),html.P('All source review IDs, exact cohort rules and highlight verification are available in the Evidence workspace.'),
                  dcc.Link('Open evidence manifest →',href='/manifest',className='cta')],className='panel')
    ],className='page-content')


def make_named_figure():
    """Positive versus negative mentions for each named puzzle, across ratings."""
    with connection() as conn:
        tags=named_puzzle_names(conn)
        rows=conn.execute("""SELECT t.tag,t.sentiment,COUNT(DISTINCT r.id) n
             FROM review_tags t JOIN reviews r ON r.id=t.review_id
             JOIN tags d ON d.name=t.tag
             WHERE r.status='ok' AND d.grp='Puzzles'
             AND t.sentiment IN ('positive','negative') GROUP BY t.tag,t.sentiment""").fetchall()
    lookup={(r['tag'],r['sentiment']):r['n'] for r in rows}
    fig=go.Figure()
    for sent in ('positive','negative'):
        fig.add_trace(go.Bar(name=sent.capitalize(),orientation='h',y=list(reversed(tags)),
            x=[lookup.get((tag,sent),0) for tag in reversed(tags)],
            marker_color=COLOURS[sent],
            customdata=[[tag,sent,lookup.get((tag,sent),0),-1] for tag in reversed(tags)],
            hovertemplate='%{customdata[0]}<br>'+sent.capitalize()+': %{x} unique reviews<extra></extra>'))
    fig.update_layout(barmode='group',height=610,paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',font={'color':'#d6e2ed'},
        margin={'l':185,'r':20,'t':45,'b':45},
        legend={'orientation':'h','y':1.09},xaxis={'title':'Unique reviews','gridcolor':'#243444'},
        yaxis={'automargin':True})
    return fig


def make_named_related(rows):
    rows=list(reversed(rows))
    fig=go.Figure()
    for sentiment in ('positive','negative'):
        entries=[r for r in rows if r['sentiment']==sentiment]
        fig.add_trace(go.Bar(name=sentiment.capitalize(),orientation='h',x=[x['pct'] for x in entries],
            y=[x['tag']+' · '+sentiment for x in entries],marker_color=COLOURS[sentiment],
            customdata=[[x['tag'],sentiment,x['n']] for x in entries],
            hovertemplate='%{customdata[0]} · '+sentiment+'<br>%{customdata[2]} reviews (%{x:.1f}% of selected)<extra></extra>'))
    fig.update_layout(height=470,barmode='group',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},margin={'l':205,'r':12,'t':35,'b':35},legend={'orientation':'h','y':1.12},
        xaxis={'title':'% of selected reviews','gridcolor':'#243444'},yaxis={'automargin':True})
    return fig


def build_named():
    interp=load_named_interpretations()
    fresh=fingerprint(DB)==interp.get('source_dataset_sha256')
    return html.Div([
      block_title('CHAPTER 1 · WHAT WENT RIGHT','Which individual puzzles do players praise—and what accompanies that praise?',
        'Compare positive and negative mentions for each named puzzle, then open the complete matching review evidence.'),
      html.Div([html.Div([html.H3('1. Which puzzles attract the most praise?'),
        html.P('Positive and negative review mentions are displayed side by side, regardless of recommendation. Click either bar to inspect the original reviews.',className='subtle'),
        dcc.Graph(id='named-graph',figure=make_named_figure(),config={'displayModeBar':False}),
        html.Button('Clear selection',id='named-clear',className='ghost-btn'),
        html.Div(id='named-selected-summary',className='selection-summary'),
        html.Button('Explore selected puzzle reviews →',id='named-inspect',className='cta button',disabled=True)],className='panel'),
        html.Div([html.Div(id='named-related-placeholder'),
        dcc.Graph(id='named-related',style={'display':'none'})],style={'display':'none'})],className='stacked-panels single-stage'),
      block_title('STEP 2 · INTERPRETATION','What might the better-received puzzles tell us?',
          'Interpretation is stored separately from the SQL counts.'),
      html.Div([html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs revalidation','good' if fresh else 'warn')],className='pill-row'),
         html.H3(item['title']),html.P(item['claim']),html.P([html.B('Basis: '),item['basis']],className='small'),
         html.Button('Explore supporting evidence →',id='named-insight-'+str(i),className='ghost-btn')],className='panel insight')
         for i,item in enumerate(interp['interpretations'])],className='two-cols'),
      html.Div([html.H3('3. Evidence manifest'),html.P('All puzzle-level source review IDs and exact tag sentiment conditions can be inspected in the Evidence workspace.'),
          dcc.Link('Open evidence manifest →',href='/manifest',className='cta')],className='panel')
    ],className='page-content')


def make_unexpected_figure():
    """Two recommendation bars; hue family is recommendation, shade/pattern is overall sentiment."""
    with connection() as conn: grouped={r:recommended_sentiment_summary(conn,r) for r in (1,0)}
    fig=go.Figure()
    for rating,label in ((1,'Recommended'),(0,'Not recommended')):
        for sent in STAGE_SENTIMENTS:
            x=next((a for a in grouped[rating] if a['sentiment']==sent),None)
            if not x:continue
            fig.add_trace(go.Bar(name=label+' · '+sent.capitalize(),x=[label],y=[x['n']],
              customdata=[[rating,sent,x['n']]],marker=stage_marker(rating,sent),
              text=[str(x['n']) if x['n']>8 else ''],textposition='inside',
              hovertemplate='%{x} · '+sent.capitalize()+'<br>%{y} reviews<extra></extra>'))
    fig.update_layout(barmode='stack',paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},height=410,margin={'l':35,'r':20,'t':95,'b':18},
        legend={'orientation':'h','y':1.35,'font':{'size':10}},yaxis={'title':'Reviews','gridcolor':'#243444'})
    return fig


def make_unexpected_related(rows):
    fig=go.Figure()
    for sent in ('positive','negative'):
        subset=[r for r in reversed(rows) if r['sentiment']==sent]
        fig.add_trace(go.Bar(orientation='h',name=sent.capitalize(),marker_color=COLOURS[sent],
            y=[r['tag']+' · '+sent for r in subset],x=[r['pct'] for r in subset],
            customdata=[[r['tag'],sent,r['n'],r['population_n']] for r in subset],
            hovertemplate='%{customdata[0]} · '+sent+'<br>%{customdata[2]} / %{customdata[3]} matching reviews (%{x:.1f}%)<extra></extra>'))
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},height=480,margin={'l':240,'r':20,'t':28,'b':40},
        legend={'orientation':'h','y':1.14},xaxis={'title':'% of selected reviews','gridcolor':'#243444'},
        yaxis={'automargin':True})
    return fig


def build_unexpected():
    interpretations=load_unexpected_interpretations()
    fresh=fingerprint(DB)==interpretations.get('source_dataset_sha256')
    return html.Div([
      block_title('CHAPTER 3 · UNEXPECTED FINDINGS','Why do some recommendations contain criticism—and some rejections contain praise?',
        'Recommendation is the player’s yes/no verdict; overall text sentiment is a separate classification of the written review as positive, neutral, mixed, or negative. Compare where the two agree and differ.'),
      html.Div([html.Div([html.H3('1. How does the written review sentiment compare with the recommendation verdict?'),
        html.P('Recommended / Not recommended comes from the review rating. Positive / Neutral / Mixed / Negative comes from the analysis of the full written review: “mixed” means the text contains both praise and criticism. Neither is a tag-level sentiment. Click any segment to inspect those reviews.',className='subtle'),
        dcc.Graph(id='unexpected-graph',figure=make_unexpected_figure(),config={'displayModeBar':False}),
        html.Button('Clear selection',id='unexpected-clear',className='ghost-btn'),
        html.Div(id='unexpected-selection-summary',className='selection-summary'),
        html.Button('Explore all matching reviews →',id='unexpected-inspect',className='cta button',disabled=True)],className='panel'),
      html.Div([html.H3('2. What do the selected reviewers praise or criticize?'),
        html.P('Positive and negative tag sentiment among the selected reviews. Each bar opens its exact matching evidence.',className='subtle'),
        dcc.Loading(html.Div([html.Div('Select an overall sentiment to explore.',id='unexpected-related-placeholder',className='subtle'),
          dcc.Graph(id='unexpected-related',style={'display':'none'},config={'displayModeBar':False})]),
          fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,
          overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'})],className='panel')],className='stacked-panels'),
      block_title('STEP 3 · INTERPRETATION','What can we learn from the mismatches?',
          'Interpretations are separate from the calculated counts and may change with new data.'),
      html.Div([html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs revalidation','good' if fresh else 'warn')],className='pill-row'),
          html.H3(item['title']),html.P(item['claim']),html.P([html.B('Basis: '),item['basis']],className='small'),
          html.Button('Inspect underlying reviews →',id='unexpected-insight-'+str(i),className='ghost-btn')],className='panel insight')
          for i,item in enumerate(interpretations['interpretations'])],className='two-cols'),
      html.Div([html.H3('4. Evidence manifest'),html.P('The filtered review IDs and calculation rules can be inspected in the shared Evidence workspace.'),
          dcc.Link('Open evidence manifest →',href='/manifest',className='cta')],className='panel')
    ],className='page-content')


def make_playtime_figure():
    with connection() as conn:rows=playtime_summary(conn)
    fig=go.Figure()
    for rating,label,color in ((1,'Recommended',COLOURS['positive']),(0,'Not recommended',COLOURS['negative'])):
        fig.add_trace(go.Bar(name=label,x=[r['bucket'] for r in rows],
            y=[r['recommended'] if rating==1 else r['not_recommended'] for r in rows],
            marker_color=color,customdata=[[r['bucket'],rating,r['n'],r['rate']] for r in rows],
            hovertemplate='%{x}<br>%{y} '+label.lower()+' of %{customdata[2]} reviews<br>Recommendation rate: %{customdata[3]}%<extra></extra>'))
    for r in rows:
        fig.add_annotation(x=r['bucket'],y=r['n'],text=f"{r['rate']}% recommend",showarrow=False,
            yshift=13,font={'size':11,'color':'#d6e2ed'})
    fig.update_layout(barmode='stack',height=405,paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},margin={'l':35,'r':15,'t':40,'b':20},
        legend={'orientation':'h','y':1.12},yaxis={'title':'Reviews (count)','gridcolor':'#243444'},
        xaxis={'title':'Playtime when review was posted'})
    return fig


def build_playtime():
    interpretations=load_playtime_interpretations()
    fresh=fingerprint(DB)==interpretations.get('source_dataset_sha256')
    return html.Div([
      block_title('CHAPTER 3 · UNEXPECTED FINDINGS','Why do reviews change across playtime groups?',
        'Review recommendation rates at different amounts of recorded playtime, then inspect the sentiment behind each group.'),
      html.Div([html.Div([html.H3('1. How does recommendation rate vary by playtime?'),
        html.P('Each column shows recommended (green) and not recommended (red) reviews. Click either portion to inspect that population. Playtime is measured at review time.',className='subtle'),
        dcc.Graph(id='playtime-graph',figure=make_playtime_figure(),config={'displayModeBar':False}),
        html.Button('Clear selection',id='playtime-clear',className='ghost-btn'),
        html.Div(id='playtime-summary',className='selection-summary'),
        html.Button('Explore all matching reviews →',id='playtime-inspect',className='cta button',disabled=True)],className='panel'),
        html.Div([html.H3('2. What do those players praise or criticize?'),
          html.P('Select a playtime and recommendation group to see its positive and negative tag mentions. Click any bar for all matching evidence.',className='subtle'),
          dcc.Loading(html.Div([html.Div('Select a playtime segment to explore.',id='playtime-related-placeholder',className='subtle'),
            dcc.Graph(id='playtime-related',style={'display':'none'},config={'displayModeBar':False})]),
            fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,
            overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'})],className='panel')],className='stacked-panels'),
      block_title('STEP 3 · INTERPRETATION','What might differences by playtime mean?',
        'Observed associations are separate from interpretation; the data does not track a player through time.'),
      html.Div([html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs revalidation','good' if fresh else 'warn')],className='pill-row'),
          html.H3(item['title']),html.P(item['claim']),html.P([html.B('Basis: '),item['basis']],className='small'),
          html.Button('Inspect supporting population →',id='playtime-insight-'+str(i),className='ghost-btn')],className='panel insight')
          for i,item in enumerate(interpretations['interpretations'])],className='two-cols'),
      html.Div([html.H3('4. Evidence manifest'),html.P('Exact review IDs and playtime interval rules are included in the shared Evidence workspace.'),
          dcc.Link('Open evidence manifest →',href='/manifest',className='cta')],className='panel')],className='page-content')



# Shared question -> population -> related evidence pattern for the new cases.
def candidate_figure(case):
    with connection() as conn: rows=candidate_summary(conn,case)
    fig=go.Figure()
    if case=='launch':
        fig.add_trace(go.Scatter(x=[r['day'] for r in rows],y=[r['pct'] for r in rows],
            mode='lines+markers',line={'color':'#8dc9bd','width':3},marker={'size':10},
            customdata=[[r['day'],r['n'],r['recommended']] for r in rows],
            hovertemplate='%{x}<br>%{y:.1f}% recommended<br>%{customdata[2]} of %{customdata[1]} reviews<extra></extra>'))
        fig.add_vrect(x0='2026-10-20',x1='2026-10-25',fillcolor='#d8b677',opacity=.10,line_width=0)
        fig.update_yaxes(title='Recommended (%)',range=[0,100])
    elif case in ('presentation','fandom'):
        tags=CASES[case]['tags']
        counts={}
        for r in rows:
            if r['sentiment'] in ('positive','negative'):
                counts[(r['tag'],r['sentiment'])]=counts.get((r['tag'],r['sentiment']),0)+r['n']
        # Review-level uniqueness is required even for repeated assignments.
        with connection() as conn:
            qs=conn.execute('''SELECT t.tag,t.sentiment,COUNT(DISTINCT r.id) n FROM review_tags t
                 JOIN reviews r ON r.id=t.review_id WHERE r.status='ok'
                 AND t.tag IN ('''+','.join('?' for _ in tags)+''')
                 AND t.sentiment IN ('positive','negative') GROUP BY t.tag,t.sentiment''',tags).fetchall()
        counts={(r['tag'],r['sentiment']):r['n'] for r in qs}
        for sent in ('positive','negative'):
            fig.add_trace(go.Bar(name=sent.capitalize(),x=list(tags),
                y=[counts.get((tag,sent),0) for tag in tags],
                marker_color=COLOURS[sent],
                customdata=[[tag,-1,sent] for tag in tags],
                hovertemplate='%{x}<br>'+sent.capitalize()+': %{y} unique reviews<extra></extra>'))
        fig.update_layout(barmode='group')
        fig.update_yaxes(title='Unique reviews mentioning the tag')
    else:
        tags=CASES[case]['tags']
        lookup={(r['tag'],r['rating'],r['sentiment']):r['n'] for r in rows}
        for rating in STAGE_RATINGS:
            label='Recommended' if rating else 'Not recommended'
            for sent in STAGE_SENTIMENTS:
                fig.add_trace(go.Bar(name=label+' · '+sent.capitalize(),
                    x=list(tags),
                    y=[lookup.get((tag,rating,sent),0) for tag in tags],
                    marker=stage_marker(rating,sent),
                    customdata=[[tag,rating,sent] for tag in tags],
                    hovertemplate='%{customdata[0]}<br>'+label+' · '+sent.capitalize()+': %{y} reviews<extra></extra>'))
        fig.update_layout(barmode='stack')
        fig.update_yaxes(title='Sentiment-specific review mentions')
    fig.update_layout(paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},margin={'l':40,'r':15,'t':100 if case!='launch' else 36,'b':78 if case!='launch' else 40},
        height=525 if case!='launch' else 370,legend={'orientation':'h','y':1.30,'font':{'size':10}},
        yaxis={'gridcolor':'#243444'})
    return fig


def candidate_interpretation(case):
    record=json.loads((ROOT/'interpretations'/(case+'.json')).read_text(encoding='utf-8'))
    fresh=record.get('source_dataset_sha256')==fingerprint(DB)
    return html.Div([html.Div([pill('INTERPRETATION','info'),pill('Current dataset' if fresh else 'Needs review','good' if fresh else 'warn')],className='pill-row'),
        html.H3(record['title']),html.P(record['claim']),
        html.P([html.B('Basis: '),record['basis']],className='small'),
        html.Button('Open evidence for this finding →',id=case+'-insight',className='ghost-btn')],className='panel insight')


def technical_overlap_figure():
    with connection() as conn: rows=technical_named_overlap(conn)
    puzzles=sorted({r['puzzle'] for r in rows})
    techs=['Progression blockers','Bugs & glitches','Crashes & black screens',
           'Save & progress','Multiplayer connectivity','Voice chat']
    lookup={(r['puzzle'],r['technical']):r for r in rows}
    fig=go.Figure(go.Heatmap(x=techs,y=puzzles,
         z=[[lookup[p,t]['pct_of_puzzle_negative'] for t in techs] for p in puzzles],
         customdata=[[[p,t,lookup[p,t]['n'],lookup[p,t]['puzzle_negative_n']] for t in techs] for p in puzzles],
         colorscale=[[0,'#172e3b'],[.35,'#376e70'],[1,'#dc7970']],
         colorbar={'title':'% of negative puzzle reviews'},
         hovertemplate='<b>%{customdata[0]}</b><br>Also negative about %{customdata[1]}: %{customdata[2]} / %{customdata[3]} puzzle reviews (%{z:.1f}%)<extra></extra>'))
    fig.update_layout(height=560,paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
         font={'color':'#d6e2ed'},margin={'l':175,'r':45,'t':20,'b':110},xaxis={'tickangle':-25})
    return fig

def build_candidate(case):
    data=CASES[case]
    islaunch=case=='launch'
    if islaunch:
        comparisons=launch_comparison_from_db()
        daycards=[html.Div([html.H3(r['day']),html.P(f"{r['recommended']} / {r['n']} recommended ({r['recommendation_rate']}%)"),
            html.P(f"Average review-time playtime: {r['average_playtime_hours']} hours",className='small subtle'),
            html.Button('Inspect all reviews this day →',id=f'launch-day-{r["day"]}',className='ghost-btn')],className='panel') for r in comparisons]
        comparison_tags=['Voice chat','Progression blockers','Puzzle & level design','Guidance & clarity','Series comparison','Story & atmosphere']
        differences=[html.Tr([html.Td(t)]+[html.Td(f"{100*r['negative_tags'].get(t,0)/r['n']:.1f}%") for r in comparisons]) for t in comparison_tags]
        second_intro=html.Div([html.H3('2. What changed in what players reported?'),
          html.P('Compare October 20 and October 25 using the same denominators: all reviews on each date. A selected day reveals the positive/negative tags and original reviews.',className='subtle'),
          html.Div(daycards,className='two-cols'),
          html.Table([html.Thead(html.Tr([html.Th('Negative tag sentiment'),html.Th('Oct 20'),html.Th('Oct 25')])),html.Tbody(differences)],className='compare-table')])
    elif case in ('fandom','motion'):
        with connection() as conn:
            if case=='fandom':
                base=candidate_ids(conn,'fandom',rating=0,tag='Anticipation & fandom',sentiment='positive')
                overlap=candidate_ids(conn,'fandom',rating=0,tag='Anticipation & fandom',sentiment='positive',related_tag='Series comparison',related_sentiment='negative')
                focal_text=f'{len(overlap)} of {len(base)} non-recommended reviewers who praise the franchise also negatively compare this game with earlier entries.'
                caution='Franchise praise may refer to past games rather than positive co-op in this installment. The tags show co-mentions, not why a player rejected the game.'
            else:
                recommended=candidate_ids(conn,'motion',rating=1,tag='Motion sickness',sentiment='negative')
                not_recommended=candidate_ids(conn,'motion',rating=0,tag='Motion sickness',sentiment='negative')
                focal_text=f'{len(recommended)} recommended and {len(not_recommended)} non-recommended reviews report negative motion-sickness sentiment.'
                caution='A review that mentions both motion sickness and a mechanic does not prove the mechanic caused the discomfort.'
        second_intro=html.Div([html.H3('2. What does the contrast reveal?'),
            html.P(focal_text,className='key-observation'),
            html.P(caution,className='subtle'),
            html.P('Select a chart segment to compare positive and negative tags in that exact group. Click a related tag to open all matching reviews.',className='subtle')])
    else:
        second_intro=html.Div([html.H3('2. What else do these reviewers mention?'),
          html.P('Select a segment and open its complete matching evidence using the button under the chart.',className='subtle')])
    technical_extra=(html.Div([html.H3('2. Which named puzzles also appear in technical complaints?'),
        html.P('Each cell counts reviews with NEGATIVE sentiment for both the named puzzle and the technical issue. The % uses reviews negative about that specific puzzle as its denominator. Co-mentions do not prove the technical issue occurred in that puzzle.',className='subtle'),
        dcc.Graph(id='technical-puzzle-overlap',figure=technical_overlap_figure(),config={'displayModeBar':False}),
        html.P('Click any cell to inspect every overlapping review and its highlighted tags.',className='hint')],className='panel') if case=='technical' else None)
    return html.Div([block_title('CHAPTER '+str(data['chapter'])+' · '+('WHAT WENT WELL' if data['chapter']==1 else 'WHAT WENT WRONG' if data['chapter']==2 else 'UNEXPECTED FINDINGS'),
        data['title'],data['description']),
      html.Div([html.Div([html.H3('1. '+('How did recommendations change each day?' if islaunch else 'Which reviewers mention these experiences positively or negatively?')),
        html.P('Click a date to explore that day.' if islaunch else ('Positive (green) versus negative (red) review mentions; click a bar to inspect its reviews.' if case in ('presentation','fandom') else 'Each topic has one stacked bar combining recommendation and sentiment.'),className='subtle'),
        dcc.Graph(id=case+'-graph',figure=candidate_figure(case),config={'displayModeBar':False}),
        html.Button('Clear selection',id=case+'-clear',className='ghost-btn'),
        html.Div(id=case+'-selection-summary',className='selection-summary'),
        html.Button('Explore all reviews in the selection →',id=case+'-inspect',disabled=True,className='cta button')],className='panel'),
      html.Div([second_intro,dcc.Loading(html.Div([html.Div('Select a population to examine its tag sentiments.',id=case+'-placeholder',className='subtle'),
        dcc.Graph(id=case+'-related',style={'display':'none'},config={'displayModeBar':False})]),
        fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,
        overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'})],className='panel',style={'display':'none'} if case in ('presentation','technical') else {})],className=('stacked-panels single-stage' if case in ('presentation','technical') else 'stacked-panels')),
      technical_extra,
      block_title('STEP '+('3' if case=='technical' else '2' if case=='presentation' else '3')+' · INTERPRETATION','What does the pattern suggest?',
        'The interpretation is maintained separately from the database calculations.'),candidate_interpretation(case),
      html.Div([html.H3(('3' if case=='presentation' else '4')+'. Evidence manifest'),html.P('Calculation rules, review IDs and evidence-span validity are available in the shared evidence workspace.'),
        dcc.Link('Open evidence manifest →',href='/manifest',className='cta')],className='panel')],className='page-content')


def launch_comparison_from_db():
    with connection() as conn:return launch_comparison(conn)

def all_sentiment_manifest(conn,sentiment):
    a=recommended_manifest(conn,DB,sentiment,rating=1)
    b=recommended_manifest(conn,DB,sentiment,rating=0)
    ids=sorted(a['population']['review_ids']+b['population']['review_ids'])
    a['definition']['rating']=None
    a['population']={'n_reviews':len(ids),'review_ids':ids}
    from analytics.engine import evidence_quality_for_tags
    a['evidence_quality']=evidence_quality_for_tags(conn,ids,[r[0] for r in conn.execute('SELECT name FROM tags')])
    return a


def build_manifest():
    return html.Div([block_title('AUDIT WORKSPACE','Evidence manifest & reproducibility',
            'The manifest is generated from the current SQLite file, not copied from a fixed report.'),
       html.Div([html.Div([html.Label('Case'),dcc.Dropdown(id='manifest-topic',options=[{'label':'Co-op','value':'coop'},{'label':'Puzzle frustration','value':'puzzles'},{'label':'Named puzzles','value':'named'},{'label':'Recommendation and sentiment','value':'unexpected'},{'label':'Playtime','value':'playtime'}]+[{'label':CASES[k]['title'],'value':k} for k in CASES],value='coop',clearable=False)],className='filter'),
         html.Div([html.Label('Recommendation'),dcc.Dropdown(id='manifest-rating',options=[{'label':'All recommendations','value':'all'},{'label':'Recommended','value':'1'},{'label':'Not recommended','value':'0'}],value='all',clearable=False)],className='filter'),
         html.Div([html.Label('Tag sentiment / issue'),dcc.Dropdown(id='manifest-sentiment',options=[{'label':'All sentiments / issues','value':'all'}]+[{'label':v.capitalize(),'value':v} for v in ('positive','negative','mixed','neutral')],value='all',clearable=False)],className='filter')],className='three-cols'),
       dcc.Loading(html.Div(id='manifest-summary',className='panel'),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'}),
       html.Div([html.Button('Download full evidence manifest (JSON)',id='download-manifest',className='cta button'),
         html.Button('Open matching reviews',id='manifest-evidence',className='ghost-btn')],className='action-row'),
       html.Div([html.H3('How it works'),html.P('A cohort is a set of unique reviews satisfying the selected case, recommendation and tag conditions. All original assignments are preserved in the evidence explorer.'),
         html.P('The JSON includes the dataset SHA-256, the deterministic filter definition, matching review IDs, population counts, and span-quality totals.'),
         html.P('Review quotations with invalid offsets remain visible but are not incorrectly highlighted.')],className='panel')],className='page-content')


def sentiment_checklist(identifier):
    return dcc.Checklist(id=identifier,
       options=[{'label':v.capitalize(),'value':v} for v in STAGE_SENTIMENTS],
       value=list(STAGE_SENTIMENTS),inline=True,className='playground-sentiments')

PATCH_EVENTS=(('2026-10-23','Patch 1.1.2'),('2026-10-30','Patch 1.1.3'),
              ('2026-11-09','Patch 1.2'),('2026-11-19','Hotfix 1.2.1'))

def review_volume_figure():
    """Daily recommendation counts; patch dates are markers, not causal claims."""
    with connection() as conn:
        rows=conn.execute("""SELECT substr(date,1,10) day,
              SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) recommended,
              SUM(CASE WHEN rating=0 THEN 1 ELSE 0 END) not_recommended
              FROM reviews WHERE status='ok' GROUP BY substr(date,1,10) ORDER BY day""").fetchall()
    fig=go.Figure()
    days=[r['day'] for r in rows]
    fig.add_bar(name='Recommended',x=days,y=[r['recommended'] for r in rows],
        marker_color='#a0d6b5',customdata=[[r['recommended']] for r in rows],
        hovertemplate='%{x}<br>Recommended: %{y}<extra></extra>')
    fig.add_bar(name='Not recommended',x=days,y=[-r['not_recommended'] for r in rows],
        marker_color='#e6a7af',customdata=[[r['not_recommended']] for r in rows],
        hovertemplate='%{x}<br>Not recommended: %{customdata[0]}<extra></extra>')
    for day,title in PATCH_EVENTS:
        fig.add_shape(type='line',xref='x',yref='paper',x0=day,x1=day,y0=0,y1=1,
            line={'color':'#e2bf76','width':1.5,'dash':'dot'})
        fig.add_annotation(x=day,y=1.08,yref='paper',text=title+'<br>'+day[5:],
            showarrow=False,font={'size':10,'color':'#f4d69b'},textangle=-35)
    last=max(days) if days else '2026-10-20'
    from datetime import date,timedelta
    end=max(date.fromisoformat(last),date(2026,11,19))+timedelta(days=2)
    fig.update_layout(barmode='relative',height=465,
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',font={'color':'#d6e2ed'},
        margin={'l':58,'r':16,'t':115,'b':65},legend={'orientation':'h','y':1.3},
        xaxis={'type':'date','range':['2026-10-19',end.isoformat()], 'tickformat':'%d %b',
               'showgrid':False,'tickangle':-35},
        yaxis={'title':'Reviews per day (negative below zero)','gridcolor':'#283849','zeroline':True,
               'zerolinecolor':'#a4b9c8'})
    return fig

def build_playground():
    with connection() as conn: tags=[{'label':t,'value':t} for t in all_tags(conn)]
    # filters are intentionally independent of all narrative cases
    return html.Div([block_title('DATA PLAYGROUND · FREE EXPLORATION',
       'Find reviews by tag, sentiment and overlap',
       'Explore any tag, compare it with another, watch sentiment over time, and inspect original reviews. No editorial conclusions are applied.'),
       html.Div([html.H3('Total reviews over time'),
           html.P('Recommended reviews are above zero; not recommended below. Patch dates are reference markers only, not evidence of patch impact. The graph shows only dates present in this database.',className='subtle'),
           dcc.Graph(id='pg-volume',figure=review_volume_figure(),config={'displayModeBar':False}),
           html.P('No reviews appear beyond the latest date in the loaded database; later patch markers remain visible for future data updates.',className='small subtle')],className='panel'),
       html.Div([
          html.Div([html.Label('Primary tag'),dcc.Dropdown(id='pg-tag',options=tags,value=None,
              placeholder='All tags (no filter)',clearable=True),html.Label('Primary sentiment'),sentiment_checklist('pg-sentiments')],className='filter'),
          html.Div([html.Label('Recommendation'),dcc.Dropdown(id='pg-rating',options=[
               {'label':'All recommendations','value':'all'}, {'label':'Recommended','value':'1'},
               {'label':'Not recommended','value':'0'}],value='all',clearable=False),
               html.Button('＋ Compare with another tag',id='pg-toggle-compare',n_clicks=0,className='ghost-btn'),
               html.Div([html.Label('Comparison tag (AND)'),dcc.Dropdown(id='pg-compare-tag',options=tags,
                   placeholder='Select comparison tag',clearable=True),
                   html.Label('Comparison sentiment'),sentiment_checklist('pg-compare-sentiments')],
                   id='pg-compare-fields',style={'display':'none'})],className='filter')
        ],className='panel playground-controls'),
       html.Div([html.H3('Sentiment evolution over time'),
           html.P('By default, each tag timeline includes ALL its sentiments, independently of the review-list sentiment filters. Use Timeline population to switch to the exact filtered cohort. Columns show the share of unique review/sentiment mentions; the line shows distinct review volume. Multi-sentiment reviews may contribute to multiple segments.',className='subtle'),
           html.Div([html.Label('Timeline population'),dcc.Dropdown(id='pg-timeline-scope',options=[
               {'label':'All mentions of each selected tag','value':'all'},
               {'label':'Only matching filtered reviews','value':'filtered'}],value='all',clearable=False)],className='filter'),
           html.Div([html.Label('Time aggregation'),dcc.Dropdown(id='pg-grain',options=[
               {'label':'Daily','value':'day'},{'label':'Weekly','value':'week'}],value='day',clearable=False)],className='filter'),
           dcc.Loading(html.Div(id='pg-timelines'),type='circle')],className='panel'),
       html.Div([html.H3('Matching original reviews'),html.Div(id='pg-count',className='pg-count'),
           html.Div([html.Button('Export matching reviews (.json)',id='pg-export',className='ghost-btn'),
                     html.Span('Exports the entire current selection.',className='subtle small')],className='action-row'),
           html.Div([html.Div([html.Label('Search review text or ID'),dcc.Input(id='pg-search',value='',type='text',debounce=True,
                placeholder='Optional search')],className='filter'),
               html.Div([html.Label('Sort'),dcc.Dropdown(id='pg-sort',options=[
                    {'label':'Newest first','value':'recent'},{'label':'Oldest first','value':'oldest'},
                    {'label':'Most helpful','value':'helpful'}],value='recent',clearable=False)],className='filter'),
               html.Div([html.Label('Language'),dcc.Dropdown(id='pg-language',options=[
                 {'label':'All languages','value':'all'}]+[{'label':('Unspecified' if x['language']=='unknown' else x['language'])+' · '+str(x['n']),
                 'value':x['language']} for x in language_options()],value='all',clearable=False)],className='filter')],className='three-cols'),
           dcc.Loading(html.Div(id='pg-review-list',className='playground-list'),type='circle'),
           html.Div([html.Button('← Previous',id='pg-prev',className='ghost-btn'),
              html.Span(id='pg-page-label'),html.Button('Next →',id='pg-next',className='ghost-btn')],className='pager')],className='panel playground-results')
    ],className='page-content')

def build_about():
    return html.Div([block_title('METHOD & STATUS','How to read these findings'),
      html.Div([html.H3('Analytics vs. interpretation'),html.P('All review counts and tag associations come from read-only SQLite queries. Interpretations live in interpretations/coop.json, with a recorded dataset fingerprint and limitations.'),
        html.H3('Denominators and duplicate tags'),html.P('Reviews are deduplicated for each review–tag–sentiment combination. A review with more than one sentiment for the same tag can appear in multiple segments. The evidence viewer retains all assignments.'),
        html.H3('Strength of evidence'),html.P('Co-occurrences are associations, not causal conclusions. Robustness checks are optional context rather than a required publication gate. No manual theme or counterexample audit is mandatory.'),
        html.H3('Browser deployment'),html.P('The app runs as a local Python web server. Anyone with repository and database access can open it in a desktop browser. Optional team hosting can be configured later.'),
        html.H3('Current scope'),html.P('This build has ten navigable cases across three chapters, including presentation, technical progression and the October 20–25 shift.')],className='panel')],className='page-content')

app=Dash(__name__,title='Review Intelligence',suppress_callback_exceptions=True,
         assets_folder=str(ROOT/'assets'))
server=app.server

@server.get('/healthz')
def railway_health():
    """Lightweight availability check for Railway."""
    from flask import jsonify
    return jsonify(status='ok' if DB.is_file() else 'missing_database', database_present=DB.is_file()), (200 if DB.is_file() else 503)
app.layout=html.Div([
   dcc.Location(id='route',refresh=False),dcc.Store(id='drawer-state',data={'open':False}),
   dcc.Download(id='evidence-json-file'),dcc.Download(id='playground-json-file'),dcc.Download(id='review-json-file'),
   dcc.Store(id='page-state',data=1),dcc.Store(id='pg-page-store',data=1),dcc.Store(id='coop-selection',data=None),dcc.Store(id='puzzle-selection',data=None),dcc.Store(id='named-selection',data=None),dcc.Store(id='unexpected-selection',data=None),dcc.Store(id='playtime-selection',data=None),dcc.Store(id='chip-scroll-signal'),*[dcc.Store(id=k+'-selection',data=None) for k in CASES],dcc.Download(id='manifest-file'),
   html.Aside([html.Div([html.Div('RI',className='logo'),html.Div([html.Strong('REVIEW'),html.Span('INTELLIGENCE')],className='brand-copy')],className='brand'),
     html.Div('EXPLORE',className='nav-head'),
     dcc.Link('Playground · Explore data',href='/playground',className='nav-link',id='nav-playground'),
     dcc.Link('All chapters · Report',href='/chapters',className='nav-link',id='nav-home'),
     html.Div('CHAPTER 1 · WHAT WENT WELL',className='nav-head'),
     dcc.Link('Co-op experience',href='/coop',className='nav-link',id='nav-coop'),
     dcc.Link('Named puzzles',href='/named-puzzles',className='nav-link',id='nav-named'),
     dcc.Link('Art vs story',href='/presentation',className='nav-link'),
     html.Div('CHAPTER 2 · WHAT WENT WRONG',className='nav-head'),
     dcc.Link('Puzzle frustration',href='/puzzles',className='nav-link',id='nav-puzzles'),
     dcc.Link('Technical progression',href='/technical',className='nav-link'),
     dcc.Link('Fandom & expectations',href='/fandom',className='nav-link'),
     html.Div('CHAPTER 3 · UNEXPECTED',className='nav-head'),
     dcc.Link('Recommendation vs sentiment',href='/mixed-recommendations',className='nav-link',id='nav-unexpected'),
     dcc.Link('Playtime differences',href='/playtime',className='nav-link',id='nav-playtime'),
     dcc.Link('October 20–25 shift',href='/launch',className='nav-link'),
     dcc.Link('Motion sickness',href='/motion',className='nav-link'),
     html.Div('AUDIT',className='nav-head'),
     dcc.Link('Evidence manifest',href='/manifest',className='nav-link',id='nav-manifest'),
     dcc.Link('Methodology',href='/about',className='nav-link',id='nav-about'),
     html.Div('Local / read-only SQLite',className='sidebar-footer')],className='sidebar'),
   html.Main([html.Div(id='home-page',children=build_home(),style={'display':'none'}),
             html.Div(id='playground-page',children=build_playground()),
             html.Div(id='coop-page',children=build_coop(),style={'display':'none'}),
             html.Div(id='puzzles-page',children=build_puzzles(),style={'display':'none'}),
             html.Div(id='named-page',children=build_named(),style={'display':'none'}),
             html.Div(id='unexpected-page',children=build_unexpected(),style={'display':'none'}),
             html.Div(id='playtime-page',children=build_playtime(),style={'display':'none'}),
             html.Div(id='manifest-page',children=build_manifest(),style={'display':'none'}),
             html.Div(id='about-page',children=build_about(),style={'display':'none'}),
             *[html.Div(id=k+'-page',children=build_candidate(k),style={'display':'none'}) for k in CASES]],className='main-content'),
   html.Div(id='drawer-shell',className='drawer-shell hidden',children=[
      html.Div(id='drawer-scrim',className='drawer-scrim'),
      html.Div([html.Div([html.Div([html.Div('EVIDENCE EXPLORER',className='eyebrow'),html.H2(id='drawer-title')]),
          html.Button('✕ Close',id='drawer-close',className='ghost-btn')],className='drawer-top'),
          html.Div(id='drawer-rule',className='rule-line'),
          html.Div([html.Button('Export selected evidence (.json)',id='evidence-export',className='ghost-btn'),
                    html.Span('Exports all matching reviews, not only this page.',className='subtle small')],className='action-row'),
          html.Div([html.Div([html.Label('Search review text / ID'),dcc.Input(id='evidence-search',debounce=True,placeholder='Search within this cohort...',type='text',value='')],className='filter'),
          html.Div([html.Label('Language'),dcc.Dropdown(id='evidence-language',options=[{'label':'All languages','value':'all'}]+[{'label':('Unspecified (metadata missing)' if x['language']=='unknown' else x['language'])+' · '+str(x['n']),'value':x['language']} for x in language_options()],value='all',clearable=False)],className='filter'),
          html.Div([html.Label('Sort'),dcc.Dropdown(id='evidence-sort',options=[{'label':'Newest','value':'recent'},{'label':'Oldest','value':'oldest'},{'label':'Most helpful','value':'helpful'}],value='recent',clearable=False)],className='filter')],className='three-cols'),
          dcc.Loading(html.Div([html.Div(id='evidence-count',className='subtle'),
          html.Div(id='evidence-list',className='evidence-list')]),fullscreen=True,custom_spinner=html.Div([html.Div(className='loader-ring'),html.Div('Loading evidence…',className='loader-label')],className='loader-screen'),delay_show=150,overlay_style={'backgroundColor':'rgba(0,0,0,0.30)','visibility':'visible'}),
          html.Div([html.Button('← Previous',id='prev-page',className='ghost-btn'),html.Span(id='page-indicator'),html.Button('Next →',id='next-page',className='ghost-btn')],className='pager')
      ],className='drawer')
   ])
])

@app.callback([Output('playground-page','style'),Output('home-page','style'),Output('coop-page','style'),Output('puzzles-page','style'),Output('named-page','style'),Output('unexpected-page','style'),Output('playtime-page','style'),Output('manifest-page','style'),Output('about-page','style')]+[Output(k+'-page','style') for k in CASES],Input('route','pathname'))
def route(path):
    path=path or '/'
    if path=='/':path='/playground'
    return [{'display':'block' if path==p else 'none'} for p in ('/playground','/chapters','/coop','/puzzles','/named-puzzles','/mixed-recommendations','/playtime','/manifest','/about')+tuple('/'+k for k in CASES)]

@app.callback(Output('coop-selection','data'),Output('rating-select','value'),Output('sentiment-select','value'),
    Input('matrix-graph','clickData'),Input('rating-select','value'),Input('sentiment-select','value'),Input('coop-clear','n_clicks'),
    State('coop-selection','data'),prevent_initial_call=True)
def update_coop_selection(click,r,s,clear,selected):
    trigger=ctx.triggered_id
    if trigger=='coop-clear':return None,None,None
    if trigger=='matrix-graph' and click and click.get('points'):
        data=click['points'][0].get('customdata')
        if data:
            candidate={'rating':int(data[0]),'sentiment':data[1]}
            if candidate==selected:return None,None,None
            return candidate,candidate['rating'],candidate['sentiment']
    if trigger in ('rating-select','sentiment-select'):
        if r is None or s is None:return None,no_update,no_update
        return {'rating':int(r),'sentiment':s},no_update,no_update
    return no_update,no_update,no_update

@app.callback(Output('selected-summary','children'),Output('related-graph','figure'),Output('related-graph','style'),Output('related-placeholder','style'),Output('inspect-cohort','disabled'),
    Input('coop-selection','data'),Input('sort-select','value'))
def update_comparisons(selection,sort):
    if not selection:
        return html.Span('No segment selected. Click a bar to explore.',className='subtle'),go.Figure(),{'display':'none'},{'display':'block'},True
    r=selection['rating'];s=selection['sentiment']
    with connection() as conn:
        ids=population_ids(conn,r,s)
        denominator=baseline(conn)['recommended' if int(r)==1 else 'not_recommended']
        related=related_comparisons(conn,r,s,sort=sort)
    summary=html.Div([html.Strong(f'{len(ids)} matching reviews'),
        html.Span(f' · {len(ids)/denominator*100:.1f}% of the {denominator:,} {"recommended" if r==1 else "not recommended"} reviews',className='subtle')])
    return summary,make_related_figure(related),{'display':'block'},{'display':'none'},False

@app.callback(Output('puzzle-selection','data'),Input('puzzle-graph','clickData'),Input('puzzle-clear','n_clicks'),
              State('puzzle-selection','data'),prevent_initial_call=True)
def update_puzzle_selection(click,clear,selected):
    if ctx.triggered_id=='puzzle-clear':return None
    if click and click.get('points'):
        data=click['points'][0].get('customdata')
        if data:
            candidate={'rating':None if int(data[0])<0 else int(data[0]),'issue':data[1],'sentiment':data[2]}
            return None if candidate==selected else candidate
    return no_update

@app.callback(Output('puzzle-selected-summary','children'),Output('puzzle-related','figure'),Output('puzzle-related','style'),Output('puzzle-related-placeholder','style'),Output('puzzle-inspect','disabled'),
              Input('puzzle-selection','data'))
def update_puzzle_comparison(selection):
    if not selection:
        return html.Span('No issue selected.',className='subtle'),go.Figure(),{'display':'none'},{'display':'block'},True
    with connection() as conn:
        ids=puzzle_population_ids(conn,selection['rating'],selection['issue'],sentiment=selection['sentiment'])
        named=puzzle_related(conn,selection['rating'],selection['issue'],sentiment=selection['sentiment'])
    return html.Strong(f'{len(ids)} matching reviews'),make_puzzle_related(named),{'display':'block'},{'display':'none'},False

@app.callback(Output('drawer-state','data'),
    Input('inspect-cohort','n_clicks'),Input('related-graph','clickData'),
    Input('insight-evidence-0','n_clicks'),Input('insight-evidence-1','n_clicks'),
    Input('manifest-evidence','n_clicks'),Input('drawer-close','n_clicks'),
    Input('puzzle-inspect','n_clicks'),Input('puzzle-related','clickData'),
    Input('puzzle-insight-0','n_clicks'),
    Input('named-inspect','n_clicks'),Input('named-related','clickData'),Input('named-insight-0','n_clicks'),
    Input('unexpected-inspect','n_clicks'),Input('unexpected-related','clickData'),Input('unexpected-insight-0','n_clicks'),Input('unexpected-insight-1','n_clicks'),
    Input('playtime-inspect','n_clicks'),Input('playtime-related','clickData'),Input('playtime-insight-0','n_clicks'),
    *[Input(k+'-inspect','n_clicks') for k in CASES],
    *[Input(k+'-related','clickData') for k in CASES],
    *[Input(k+'-insight','n_clicks') for k in CASES],
    Input('launch-day-2026-10-20','n_clicks'),Input('launch-day-2026-10-25','n_clicks'),
    Input('technical-puzzle-overlap','clickData'),
    State('coop-selection','data'),State('puzzle-selection','data'),State('named-selection','data'),State('unexpected-selection','data'),State('playtime-selection','data'),
    *[State(k+'-selection','data') for k in CASES],
    State('manifest-rating','value'),State('manifest-sentiment','value'),State('manifest-topic','value'),prevent_initial_call=True)
def drawer_actions(inspect,bar,first,second,mopen,close,pinspect,pbar,pinsight,ninspect,nbar,ninsight,uinspect,ubar,uinsight0,uinsight1,tinspect,tbar,tinsight,*args):
    n=len(CASES)
    cs,ps,ns,us,ts= args[3*n+3:3*n+8]
    selections=dict(zip(CASES,args[3*n+8:4*n+8]))
    mr,ms,mt=args[-3:]
    new_related=dict(zip(CASES,args[n:2*n]))
    trigger=ctx.triggered_id
    if trigger=='drawer-close':return {'open':False}
    if trigger=='technical-puzzle-overlap':
        click=args[3*n+2]
        if click and click.get('points'):
            datum=click['points'][0].get('customdata')
            if datum and len(datum)>=2:
                return {'open':True,'topic':'technical-puzzle-overlap','puzzle':datum[0],
                        'technical':datum[1]}
        return no_update
    for k in CASES:
        if trigger==k+'-inspect' and selections.get(k):
            return {'open':True,'topic':k,**selections[k]}
        if trigger==k+'-related' and selections.get(k):
            event=new_related.get(k)
            if event and event.get('points'):
                datum=event['points'][0].get('customdata')
                if datum:return {'open':True,'topic':k,**selections[k],'related_tag':datum[0],'related_sentiment':datum[1]}
        if trigger==k+'-insight':
            return {'open':True,'topic':k,**({'day':'2026-10-25'} if k=='launch' else {'rating':0,'tag':'Anticipation & fandom','sentiment':'positive','related_tag':'Series comparison','related_sentiment':'negative'} if k=='fandom' else {'rating':1,'tag':'Motion sickness','sentiment':'negative'} if k=='motion' else {'rating':0,'tag':CASES[k]['focus'][0],'sentiment':'negative'})}
    if trigger in ('launch-day-2026-10-20','launch-day-2026-10-25'):
        return {'open':True,'topic':'launch','day':trigger[-10:]}

    if trigger=='related-graph':
        if not cs or not bar or not bar.get('points'):return no_update
        data=bar['points'][0].get('customdata')
        if not data:return no_update
        return {'open':True,'topic':'coop','rating':cs['rating'],'sentiment':cs['sentiment'],'related_tag':data[0],'related_sentiment':data[1]}
    if trigger=='insight-evidence-0':return {'open':True,'topic':'coop','rating':1,'sentiment':'positive','insight_idx':0}
    if trigger=='insight-evidence-1':return {'open':True,'topic':'coop','rating':0,'sentiment':'negative','insight_idx':1}
    if trigger=='unexpected-inspect' and us:return {'open':True,'topic':'unexpected',**us}
    if trigger=='unexpected-related' and us and ubar and ubar.get('points'):
        data=ubar['points'][0].get('customdata')
        if data:return {'open':True,'topic':'unexpected',**us,'related_tag':data[0],'related_sentiment':data[1]}
    if trigger=='unexpected-insight-0':return {'open':True,'topic':'unexpected','rating':1,'sentiment':'mixed','insight_idx':0}
    if trigger=='unexpected-insight-1':return {'open':True,'topic':'unexpected','rating':0,'sentiment':'mixed','insight_idx':1}
    if trigger=='playtime-inspect' and ts:return {'open':True,'topic':'playtime',**ts}
    if trigger=='playtime-related' and ts and tbar and tbar.get('points'):
        data=tbar['points'][0].get('customdata')
        if data:return {'open':True,'topic':'playtime',**ts,'related_tag':data[0],'related_sentiment':data[1]}
    if trigger=='playtime-insight-0':return {'open':True,'topic':'playtime','bucket':'6–12 hours','insight_idx':0}
    if trigger=='manifest-evidence':
        if mt in CASES:return {'open':True,'topic':mt,'rating':None if mr=='all' else int(mr),**({'day':None if ms=='all' else ms} if mt=='launch' else {'tag':None if ms=='all' else ms})}
        if mt=='unexpected':return {'open':True,'topic':'unexpected','rating':None if mr=='all' else int(mr),'sentiment':None if ms=='all' else ms}
        if mt=='playtime':return {'open':True,'topic':'playtime','rating':None if mr=='all' else int(mr),'bucket':None if ms=='all' else ms}
        if mt=='puzzles':return {'open':True,'topic':'puzzles','rating':None if mr=='all' else int(mr),'issue':None if ms=='all' else ms}
        if mt=='named':return {'open':True,'topic':'named','rating':None if mr=='all' else int(mr),'tag':None if ms=='all' else ms}
        return {'open':True,'topic':'coop','rating':None if mr=='all' else int(mr),'sentiment':None if ms=='all' else ms}
    if trigger=='inspect-cohort' and cs:return {'open':True,'topic':'coop',**cs}
    if trigger=='puzzle-inspect' and ps:return {'open':True,'topic':'puzzles',**ps}
    if trigger=='puzzle-related' and ps and pbar and pbar.get('points'):
        data=pbar['points'][0].get('customdata')
        if data and len(data)>1:return {'open':True,'topic':'puzzles',**ps,'related_tag':data[0],'related_sentiment':data[1]}
    if trigger=='puzzle-insight-0':return {'open':True,'topic':'puzzles','rating':0,'issue':None,'sentiment':'negative','insight_idx':0}
    if trigger=='named-inspect' and ns:return {'open':True,'topic':'named',**ns}
    if trigger=='named-related' and ns and nbar and nbar.get('points'):
        data=nbar['points'][0].get('customdata')
        if data:return {'open':True,'topic':'named',**ns,'related_tag':data[0],'related_sentiment':data[1]}
    if trigger=='named-insight-0':return {'open':True,'topic':'named','tag':None,'sentiment':None,'insight_idx':0}
    return no_update


def ids_for_drawer(conn,state):
    if state.get('topic')=='technical-puzzle-overlap':
        return sorted(set(filter_ids(conn,state.get('puzzle'),['negative'],state.get('technical'),['negative'])))
    if state.get('topic') in CASES:
        return candidate_ids(conn,state['topic'],rating=state.get('rating'),tag=state.get('tag'),sentiment=state.get('sentiment'),day=state.get('day'),related_tag=state.get('related_tag'),related_sentiment=state.get('related_sentiment'))
    if state.get('topic')=='unexpected':
        if state.get('rating') is None:
            return sorted(set(recommended_sentiment_ids(conn,state.get('sentiment'),state.get('related_tag'),state.get('related_sentiment'),rating=1)) | set(recommended_sentiment_ids(conn,state.get('sentiment'),state.get('related_tag'),state.get('related_sentiment'),rating=0)))
        return recommended_sentiment_ids(conn,state.get('sentiment'),state.get('related_tag'),state.get('related_sentiment'),rating=state['rating'])
    if state.get('topic')=='playtime':return playtime_ids(conn,state.get('bucket'),state.get('rating'),state.get('related_tag'),state.get('related_sentiment'))
    if state.get('topic')=='named':
        return named_puzzle_ids(conn,state.get('tag'),state.get('sentiment'),state.get('rating'),state.get('related_tag'),state.get('related_sentiment'))
    if state.get('topic')=='puzzles':
        return puzzle_population_ids(conn,state.get('rating'),state.get('issue'),sentiment=state.get('sentiment') or 'negative',related_tag=state.get('related_tag'),related_sentiment=state.get('related_sentiment'))
    return population_ids(conn,state.get('rating'),state.get('sentiment'),state.get('related_tag'),state.get('related_sentiment'))

@app.callback([Output('drawer-shell','className'),Output('drawer-title','children'),Output('drawer-rule','children')],Input('drawer-state','data'))
def drawer_view(state):
    if not state or not state.get('open'):return 'drawer-shell hidden','',''
    rating=state.get('rating');sent=state.get('sentiment');extra=state.get('related_tag');es=state.get('related_sentiment')
    with connection() as conn:
        ids=ids_for_drawer(conn,state)
        if state.get('topic')=='technical-puzzle-overlap':quality=evidence_quality_for_tags(conn,ids,[state['puzzle'],state['technical']])
        elif state.get('topic') in CASES:
            tag_scope=CASES[state['topic']]['tags'] if state['topic']!='launch' else [r[0] for r in conn.execute('SELECT name FROM tags')]
            quality=evidence_quality_for_tags(conn,ids,tag_scope)
        elif state.get('topic') in ('unexpected','playtime'):quality=evidence_quality_for_tags(conn,ids,[t[0] for t in conn.execute('SELECT name FROM tags')])
        elif state.get('topic')=='puzzles':
            issue=state.get('issue')
            tags=[issue] if issue else list(PUZZLE_ISSUES)
            quality=evidence_quality_for_tags(conn,ids,tags)
        elif state.get('topic')=='named':quality=evidence_quality_for_tags(conn,ids,[state['tag']] if state.get('tag') else named_puzzle_names(conn))
        else:quality=evidence_quality(conn,ids)
    label='Recommended' if rating==1 else 'Not recommended' if rating==0 else 'All recommendations'
    title=f'{label} · {state.get("sentiment") or "negative"} · {state.get("issue") or "any puzzle issue"}' if state.get('topic')=='puzzles' else f'{label} · {sent.capitalize() if sent else "all"} co-op'
    if state.get('topic')=='unexpected':title=f'{label} · {sent or "all"} overall sentiment'
    if state.get('topic')=='playtime':title=f'{state.get("bucket") or "All playtimes"} · {label}'
    if state.get('topic') in CASES:
        title=(state.get('day') or state.get('tag') or CASES[state['topic']]['title'])+' · '+label+' · '+(sent or 'all sentiments')
    if state.get('topic')=='technical-puzzle-overlap':title=f"Negative {state['puzzle']} + negative {state['technical']}"
    if state.get('topic')=='named':title=f'{label} · {sent or "any sentiment"} · {state.get("tag") or "all named puzzles"}'
    if extra:title+=f' + {es} {extra}'
    details=[pill(f'{len(ids)} reviews','good'),pill(f'{quality["exact_spans"]} exact spans','good'),
             pill(f'{quality["unverified_spans"]} unverified spans','warn' if quality['unverified_spans'] else 'muted'),
             html.P('Definition: analyzed reviews satisfying the selected tag, sentiment and recommendation conditions. All original tags and passages are visible below.',className='small')]
    if state.get('topic')=='technical-puzzle-overlap':
        details.append(html.P('These reviews contain negative evidence for BOTH tags. Inspect the original passages to determine whether the technical problem was reported inside that puzzle; tag overlap alone does not establish that connection.',className='small subtle'))
    idx=state.get('insight_idx')
    if idx is not None:
        interp=load_playtime_interpretations() if state.get('topic')=='playtime' else load_unexpected_interpretations() if state.get('topic')=='unexpected' else load_named_interpretations() if state.get('topic')=='named' else (load_puzzle_interpretations() if state.get('topic')=='puzzles' else load_interpretations())
        rec=interp['interpretations'][idx]
        details.append(html.Details([html.Summary('Interpretation limitation'),html.P(rec['limitations'],className='small subtle')]))
    return 'drawer-shell',title,details

@app.callback(Output('page-state','data'),Input('drawer-state','data'),Input('evidence-search','value'),Input('evidence-sort','value'),Input('evidence-language','value'),
  Input('prev-page','n_clicks'),Input('next-page','n_clicks'),State('page-state','data'),prevent_initial_call=True)
def change_page(state,search,sort,language,prev,next_,page):
    trigger=ctx.triggered_id
    if trigger in ('drawer-state','evidence-search','evidence-sort','evidence-language'):return 1
    return max(1,int(page or 1)+(-1 if trigger=='prev-page' else 1))

@app.callback([Output('evidence-count','children'),Output('evidence-list','children'),Output('page-indicator','children')],
   Input('drawer-state','data'),Input('evidence-search','value'),Input('evidence-sort','value'),Input('evidence-language','value'),Input('page-state','data'))
def render_evidence(state,search,sort,language,page):
    if not state or not state.get('open'):return '',[],''
    with connection() as conn:
        ids=ids_for_drawer(conn,state)
        reviews,total=review_page(conn,ids,page=page,search=search or '',order=sort or 'recent',language=language or 'all')
    pages=max(1,(total+7)//8)
    if int(page or 1)>pages:
        reviews=[]
    return f'{total:,} reviews match the current filters · showing up to 8 per page',[review_card(row) for row in reviews] or html.P('No reviews on this page.',className='subtle'),f'Page {page} of {pages}'

@app.callback(Output('manifest-rating','value'),Output('manifest-rating','disabled'),Input('manifest-topic','value'))
def manifest_rating_scope(topic):
    # Both recommendation groups are available in the sentiment chapter.
    return ('all',False)

@app.callback(Output('manifest-sentiment','options'),Output('manifest-sentiment','value'),Input('manifest-topic','value'))
def manifest_options(topic):
    if topic=='unexpected':return [{'label':'All overall sentiments','value':'all'}]+[{'label':v.capitalize(),'value':v} for v in ('positive','mixed','negative','neutral')],'all'
    if topic in CASES:
        return ([{'label':'All available dates','value':'all'}]+[{'label':d,'value':d} for d in ('2026-10-20','2026-10-25')] if topic=='launch' else [{'label':'All relevant tags','value':'all'}]+[{'label':tag,'value':tag} for tag in CASES[topic]['tags']]),'all'
    if topic=='playtime':return [{'label':'All playtimes','value':'all'}]+[{'label':v,'value':v} for v in ('Under 1 hour','1–3 hours','3–6 hours','6–12 hours','12–24 hours','24+ hours')],'all'
    if topic=='puzzles':return [{'label':'All three issues','value':'all'}]+[{'label':x,'value':x} for x in PUZZLE_ISSUES],'all'
    if topic=='named':
        with connection() as conn: names=named_puzzle_names(conn)
        return [{'label':'All named puzzles','value':'all'}]+[{'label':x,'value':x} for x in names],'all'
    return [{'label':'All sentiments','value':'all'}]+[{'label':v.capitalize(),'value':v} for v in ('positive','negative','mixed','neutral')],'all'

@app.callback(Output('manifest-summary','children'),Input('manifest-topic','value'),Input('manifest-rating','value'),Input('manifest-sentiment','value'))
def update_manifest(topic,r,s):
    with connection() as conn:
        data=(candidate_manifest(conn,DB,topic,rating=None if r=='all' else int(r),**({'day':None if s=='all' else s} if topic=='launch' else {'tag':None if s=='all' else s})) if topic in CASES else recommended_manifest(conn,DB,None if s=='all' else s,rating=int(r)) if topic=='unexpected' and r!='all' else playtime_manifest(conn,DB,None if s=='all' else s,None if r=='all' else int(r)) if topic=='playtime' else all_sentiment_manifest(conn,None if s=='all' else s) if topic=='unexpected' else puzzle_manifest(conn,DB,None if r=='all' else int(r),None if s=='all' else s) if topic=='puzzles' else named_puzzle_manifest(conn,DB,None if s=='all' else s,rating=None if r=='all' else int(r)) if topic=='named' else manifest(conn,DB,None if r=='all' else int(r),None if s=='all' else s))
    q=data['evidence_quality']
    return [html.H3(f"{data['population']['n_reviews']} matching unique reviews"),
      html.Div([pill(f"{q['exact_spans']} exact spans",'good'),pill(f"{q['unverified_spans']} unverified",'warn' if q['unverified_spans'] else 'muted')],className='pill-row'),
      html.P('Current dataset SHA-256: '+data['dataset_sha256'],className='mono small'),
      html.Pre(json.dumps(data['definition'],indent=2),className='code-panel'),
      html.Details([html.Summary('Preview matching review IDs'),html.P(', '.join(data['population']['review_ids'][:120]) + (' …' if len(data['population']['review_ids'])>120 else ''),className='mono small')])]

@app.callback(Output('manifest-file','data'),Input('download-manifest','n_clicks'),
   State('manifest-topic','value'),State('manifest-rating','value'),State('manifest-sentiment','value'),prevent_initial_call=True)
def export_manifest(n,topic,r,s):
    with connection() as conn:
        data=(candidate_manifest(conn,DB,topic,rating=None if r=='all' else int(r),**({'day':None if s=='all' else s} if topic=='launch' else {'tag':None if s=='all' else s})) if topic in CASES else recommended_manifest(conn,DB,None if s=='all' else s,rating=int(r)) if topic=='unexpected' and r!='all' else playtime_manifest(conn,DB,None if s=='all' else s,None if r=='all' else int(r)) if topic=='playtime' else all_sentiment_manifest(conn,None if s=='all' else s) if topic=='unexpected' else puzzle_manifest(conn,DB,None if r=='all' else int(r),None if s=='all' else s) if topic=='puzzles' else named_puzzle_manifest(conn,DB,None if s=='all' else s,rating=None if r=='all' else int(r)) if topic=='named' else manifest(conn,DB,None if r=='all' else int(r),None if s=='all' else s))
    return {'content':json.dumps(data,ensure_ascii=False,indent=2),'filename':topic+'_evidence_manifest.json','type':'application/json'}

@app.callback(Output('named-selection','data'),Input('named-graph','clickData'),Input('named-clear','n_clicks'),
              State('named-selection','data'),prevent_initial_call=True)
def choose_named(click,clear,previous):
    if ctx.triggered_id=='named-clear':return None
    if click and click.get('points'):
        data=click['points'][0].get('customdata')
        if data:
            selected={'tag':data[0],'sentiment':data[1],'rating':None if int(data[3])<0 else int(data[3])} 
            return None if selected==previous else selected
    return no_update

@app.callback(Output('named-selected-summary','children'),Output('named-related','figure'),Output('named-related','style'),
              Output('named-related-placeholder','style'),Output('named-inspect','disabled'),Input('named-selection','data'))
def update_named(selection):
    if not selection:return 'No puzzle selected.',go.Figure(),{'display':'none'},{'display':'block'},True
    with connection() as conn:
        ids=named_puzzle_ids(conn,selection['tag'],selection['sentiment'],selection.get('rating'))
    return html.Strong(f'{len(ids)} reviews · {selection["sentiment"]} {selection["tag"]}'),go.Figure(),{'display':'none'},{'display':'none'},False

@app.callback(Output('unexpected-selection','data'),Input('unexpected-graph','clickData'),Input('unexpected-clear','n_clicks'),
              State('unexpected-selection','data'),prevent_initial_call=True)
def choose_unexpected(click,clear,previous):
    if ctx.triggered_id=='unexpected-clear':return None
    if click and click.get('points'):
        data=click['points'][0].get('customdata')
        if data:
            selected={'rating':int(data[0]),'sentiment':data[1]}
            return None if selected==previous else selected
    return no_update


@app.callback(Output('unexpected-selection-summary','children'),Output('unexpected-related','figure'),
              Output('unexpected-related','style'),Output('unexpected-related-placeholder','style'),
              Output('unexpected-inspect','disabled'),Input('unexpected-selection','data'))
def update_unexpected(selection):
    if not selection:return html.Span('No overall sentiment selected.',className='subtle'),go.Figure(),{'display':'none'},{'display':'block'},True
    with connection() as conn:
        ids=recommended_sentiment_ids(conn,selection['sentiment'],rating=selection['rating'])
        related=recommended_related(conn,selection['sentiment'],rating=selection['rating'])
    group='recommended' if selection['rating']==1 else 'not recommended'
    return html.Strong(f'{len(ids)} {group} reviews · {selection["sentiment"]} overall sentiment'),make_unexpected_related(related),{'display':'block'},{'display':'none'},False


@app.callback(Output('playtime-selection','data'),Input('playtime-graph','clickData'),Input('playtime-clear','n_clicks'),
              State('playtime-selection','data'),prevent_initial_call=True)
def choose_playtime(click,clear,previous):
    if ctx.triggered_id=='playtime-clear':return None
    if click and click.get('points'):
        data=click['points'][0].get('customdata')
        if data:
            chosen={'bucket':data[0],'rating':int(data[1])}
            return None if chosen==previous else chosen
    return no_update


@app.callback(Output('playtime-summary','children'),Output('playtime-related','figure'),
              Output('playtime-related','style'),Output('playtime-related-placeholder','style'),
              Output('playtime-inspect','disabled'),Input('playtime-selection','data'))
def update_playtime(selection):
    if not selection:return html.Span('Select a playtime segment.',className='subtle'),go.Figure(),{'display':'none'},{'display':'block'},True
    with connection() as conn:
        ids=playtime_ids(conn,selection['bucket'],selection['rating'])
        related=playtime_related(conn,selection['bucket'],selection['rating'])
    return html.Strong(f'{len(ids)} reviews · {selection["bucket"]} · {"recommended" if selection["rating"] else "not recommended"}'),make_unexpected_related(related),{'display':'block'},{'display':'none'},False

# Browser-side smooth scroll keeps review text local and does not introduce additional server calls.
app.clientside_callback(
    """function(clicks) {
      const triggered = dash_clientside.callback_context.triggered;
      if (!triggered || !triggered.length || !triggered[0].value) return dash_clientside.no_update;
      try {
        const prop = triggered[0].prop_id;
        const id = JSON.parse(prop.substring(0, prop.lastIndexOf('.')));
        const anchor = document.getElementById('evidence-span-' + id.scope + '-' + id.review + '-' + id.assignment);
        if (anchor) {
          anchor.scrollIntoView({behavior:'smooth',block:'center',inline:'nearest'});
          const target=anchor.nextElementSibling;
          if (target) {
            target.classList.remove('evidence-flash'); void target.offsetWidth;
            target.classList.add('evidence-flash');
          }
        }
      } catch(e) {console.warn('Could not navigate to evidence highlight',e);}
      return Date.now();
    }""",
    Output('chip-scroll-signal','data'),Input({'type':'evidence-chip','review':dash.ALL,'assignment':dash.ALL,'scope':dash.ALL},'n_clicks'),
    prevent_initial_call=True)


# Per-candidate callbacks registered from the same deterministic calculation contract.
def register_candidate_callbacks(case):
    @app.callback(Output(case+'-selection','data'),Input(case+'-graph','clickData'),Input(case+'-clear','n_clicks'),
                  State(case+'-selection','data'),prevent_initial_call=True)
    def choose(click,clear,prev):
        if ctx.triggered_id==case+'-clear':return None
        if not click or not click.get('points'):return no_update
        data=click['points'][0].get('customdata')
        if not data:return no_update
        value={'day':data[0]} if case=='launch' else {'tag':data[0],'rating':None if int(data[1])<0 else int(data[1]),'sentiment':data[2]}
        return None if value==prev else value

    @app.callback(Output(case+'-selection-summary','children'),Output(case+'-related','figure'),
        Output(case+'-related','style'),Output(case+'-placeholder','style'),Output(case+'-inspect','disabled'),
        Input(case+'-selection','data'))
    def update(selection):
        if not selection:return html.Span('Nothing selected.',className='subtle'),go.Figure(),{'display':'none'},{'display':'block'},True
        with connection() as conn:
            ids=candidate_ids(conn,case,**selection)
            rows=[] if case in ('technical','presentation') else candidate_related(conn,case,ids)
        return html.Strong(f'{len(ids)} matching reviews · '+(' / '.join(str(v) for v in selection.values()))),(make_unexpected_related(rows) if rows else go.Figure()),({'display':'none'} if case in ('technical','presentation') else {'display':'block'}),{'display':'none'},False

for _case in CASES:register_candidate_callbacks(_case)

@app.callback(Output('pg-compare-fields','style'),Output('pg-toggle-compare','children'),
    Input('pg-toggle-compare','n_clicks'))
def compare_fields(n):
    on=bool((n or 0)%2)
    return ({'display':'block'} if on else {'display':'none'}),('− Remove comparison' if on else '＋ Compare with another tag')

def playground_query(conn,tag,sentiments,compare_active,compare_tag,compare_sentiments,rating):
    ids=filter_ids(conn,tag,sentiments,compare_tag if compare_active else None,
                   compare_sentiments if compare_active else None)
    if rating!='all':
        allowed={r[0] for r in conn.execute("SELECT id FROM reviews WHERE status='ok' AND rating=?",(int(rating),))}
        ids=[rid for rid in ids if rid in allowed]
    return ids

def pg_timeline_plot(history,tag):
    fig=go.Figure()
    for sent in STAGE_SENTIMENTS:
        fig.add_trace(go.Bar(name=sent.capitalize(),x=[r['period'] for r in history],
            y=[r[sent+'_share'] for r in history],marker_color=COLOURS[sent],
            customdata=[[r[sent],r['n_sentiment_mentions']] for r in history],
            hovertemplate='%{x}<br>'+sent.capitalize()+': %{customdata[0]} of %{customdata[1]} sentiment mentions (%{y:.1f}%)<extra></extra>'))
    fig.add_trace(go.Scatter(name='Distinct review volume',x=[r['period'] for r in history],
        y=[r['n_reviews'] for r in history],yaxis='y2',mode='lines+markers',
        line={'color':'#fff','width':2,'dash':'dot'},marker={'size':5},
        hovertemplate='%{x}<br>%{y} distinct tagged reviews<extra></extra>'))
    fig.update_layout(title=tag,barmode='stack',height=345,
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',
        font={'color':'#d6e2ed'},margin={'l':40,'r':65,'t':55,'b':60},
        legend={'orientation':'h','y':1.2},
        yaxis={'title':'Sentiment mix (%)','range':[0,100],'gridcolor':'#243444'},
        yaxis2={'title':'Distinct reviews','overlaying':'y','side':'right','showgrid':False},
        xaxis={'type':'category','tickangle':-35})
    return fig

@app.callback(Output('pg-timelines','children'),
    Input('pg-tag','value'),Input('pg-sentiments','value'),Input('pg-compare-tag','value'),
    Input('pg-compare-sentiments','value'),Input('pg-toggle-compare','n_clicks'),
    Input('pg-grain','value'),Input('pg-rating','value'),Input('pg-timeline-scope','value'))
def update_pg_timeline(tag,sents,comp,comp_sents,n,grain,rating,scope):
    if not tag and not (n or 0)%2:return html.P('Select a tag to see its sentiment evolution.',className='subtle')
    on=bool((n or 0)%2)
    with connection() as conn:
        # Timeline compares sentiment of selected tag(s), using same review-overlap filters.
        ids=(playground_query(conn,tag,sents,on,comp,comp_sents,rating) if scope=='filtered' else
             playground_query(conn,None,[],False,None,[],rating))
        panels=[]
        for t in dict.fromkeys([tag]+([comp] if on else [])):
            if not t:continue
            history=sentiment_history(conn,t,ids,grain)
            panels.append(dcc.Graph(figure=pg_timeline_plot(history,t),config={'displayModeBar':False}) if history else html.P(f'No matching dated reviews for {t}.'))
    return panels or html.P('Select a tag to see its sentiment evolution.',className='subtle')

@app.callback(Output('pg-page-store','data'),
    Input('pg-tag','value'),Input('pg-sentiments','value'),Input('pg-compare-tag','value'),
    Input('pg-compare-sentiments','value'),Input('pg-toggle-compare','n_clicks'),
    Input('pg-rating','value'),Input('pg-search','value'),Input('pg-sort','value'),
    Input('pg-language','value'),Input('pg-prev','n_clicks'),Input('pg-next','n_clicks'),
    State('pg-page-store','data'))
def update_pg_page(tag,sents,comp,comp_sents,n,rating,search,sort,lang,prev,next_,page):
    trigger=ctx.triggered_id
    if trigger in ('pg-prev','pg-next'):
        return max(1,int(page or 1)+(-1 if trigger=='pg-prev' else 1))
    return 1

@app.callback(Output('pg-count','children'),Output('pg-review-list','children'),Output('pg-page-label','children'),
    Input('pg-tag','value'),Input('pg-sentiments','value'),Input('pg-compare-tag','value'),
    Input('pg-compare-sentiments','value'),Input('pg-toggle-compare','n_clicks'),
    Input('pg-rating','value'),Input('pg-search','value'),Input('pg-sort','value'),
    Input('pg-language','value'),Input('pg-page-store','data'))
def update_pg_reviews(tag,sents,comp,comp_sents,n,rating,search,sort,lang,page):
    with connection() as conn:
        ids=playground_query(conn,tag,sents,bool((n or 0)%2),comp,comp_sents,rating)
        reviews,total=review_page(conn,ids,page=page or 1,per_page=8,search=search or '',order=sort or 'recent',language=lang or 'all')
    countpages=max(1,(total+7)//8)
    return f'{total:,} matching reviews',[review_card(row,scope='pg') for row in reviews] or html.P('No reviews on this page.',className='subtle'),f'Page {page} of {countpages}'

# Export exactly the visible evidence population (including search/language filters),
# with the original full review bodies, all tags, and span verification status.
def _evidence_download(conn,ids,filters,search='',order='recent',language='all'):
    from analytics.exports import evidence_package
    return evidence_package(conn,DB,ids,filters,search=search,order=order,language=language)


def _json_send(data,filename):
    return dcc.send_string(json.dumps(data,ensure_ascii=False,indent=2),filename)


@app.callback(Output('evidence-json-file','data'),Input('evidence-export','n_clicks'),
    State('drawer-state','data'),State('evidence-search','value'),State('evidence-sort','value'),
    State('evidence-language','value'),prevent_initial_call=True)
def export_drawer(n,state,search,sort,language):
    if not n or not state or not state.get('open'):return no_update
    with connection() as conn:
        ids=ids_for_drawer(conn,state)
        result=_evidence_download(conn,ids,state,search or '',sort or 'recent',language or 'all')
    topic=re.sub(r'[^a-z0-9_-]+','_',str(state.get('topic','evidence')).lower())
    return _json_send(result,'evidence_'+topic+'.json')


@app.callback(Output('playground-json-file','data'),Input('pg-export','n_clicks'),
    State('pg-tag','value'),State('pg-sentiments','value'),State('pg-compare-tag','value'),
    State('pg-compare-sentiments','value'),State('pg-toggle-compare','n_clicks'),
    State('pg-rating','value'),State('pg-search','value'),State('pg-sort','value'),
    State('pg-language','value'),prevent_initial_call=True)
def export_playground(n,tag,sents,compare_tag,compare_sents,compare_clicks,rating,search,sort,language):
    if not n:return no_update
    active=bool((compare_clicks or 0)%2)
    filters={'topic':'playground','tag':tag,'sentiments':sents,
             'compare_active':active,'compare_tag':compare_tag if active else None,
             'compare_sentiments':compare_sents if active else [],'rating':rating}
    with connection() as conn:
        ids=playground_query(conn,tag,sents,active,compare_tag,compare_sents,rating)
        result=_evidence_download(conn,ids,filters,search or '',sort or 'recent',language or 'all')
    return _json_send(result,'playground_evidence.json')


@app.callback(Output('review-json-file','data'),
    Input({'type':'review-json-export','review':dash.ALL,'scope':dash.ALL},'n_clicks'),
    prevent_initial_call=True)
def export_one_review(clicks):
    item=ctx.triggered_id
    if not isinstance(item,dict) or not ctx.triggered or not ctx.triggered[0]['value']:
        return no_update
    rid=str(item['review'])
    with connection() as conn:
        result=_evidence_download(conn,[rid],{'topic':'single-review','review_id':rid})
    return _json_send(result,'review_'+re.sub(r'[^0-9a-z_-]','',rid)+'.json')


@app.callback(Output({'type':'review-translation','review':dash.MATCH,'scope':dash.MATCH},'children'),
    Input({'type':'translate-button','review':dash.MATCH,'scope':dash.MATCH},'n_clicks'),
    State({'type':'translate-button','review':dash.MATCH,'scope':dash.MATCH},'id'),prevent_initial_call=True)
def translate_one_review(n,button_id):
    if not n:return no_update
    with connection() as conn:
        row=conn.execute("SELECT body FROM reviews WHERE id=? AND status='ok'",(button_id['review'],)).fetchone()
    if not row:return html.P('Review not found.',className='subtle')
    try:return html.Div([html.B('English translation · review body only'),
                         html.Div(translate_review_body(row['body']),className='translated-review')])
    except RuntimeError as e:return html.P(str(e),className='subtle')

if __name__=='__main__':
    app.run(debug=os.environ.get('DASH_DEBUG','0')=='1',host=os.environ.get('DASH_HOST','127.0.0.1'),port=int(os.environ.get('PORT',8050)))
