"""Deterministic, read-only SQLite analytics and auditable evidence populations."""
from __future__ import annotations
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

COOP = 'Co-op experience'
SENTIMENTS = ('positive', 'negative', 'mixed', 'neutral')
OTHER_TAG_LIMIT = 22
PUZZLE_ISSUES = ('Puzzle & level design', 'Guidance & clarity', 'Difficulty')


def connect(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'SQLite database not found: {path}')
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def baseline(conn):
    row = conn.execute('''SELECT COUNT(*) n,
        SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) recommended,
        SUM(CASE WHEN rating=0 THEN 1 ELSE 0 END) not_recommended
        FROM reviews WHERE status='ok' ''').fetchone()
    n_coop = conn.execute('''SELECT COUNT(DISTINCT rt.review_id) FROM review_tags rt
        JOIN reviews r ON r.id=rt.review_id
        WHERE r.status='ok' AND rt.tag=?''', (COOP,)).fetchone()[0]
    return dict(row) | {'coop_unique_reviews': n_coop}


def matrix(conn):
    out = []
    for rating in (1, 0):
        denominator = conn.execute('SELECT COUNT(*) FROM reviews WHERE status=\'ok\' AND rating=?',(rating,)).fetchone()[0]
        for sentiment in SENTIMENTS:
            n = conn.execute('''SELECT COUNT(DISTINCT r.id) FROM reviews r
                JOIN review_tags t ON t.review_id=r.id
                WHERE r.status='ok' AND r.rating=? AND t.tag=? AND t.sentiment=?''',
                (rating,COOP,sentiment)).fetchone()[0]
            out.append({'rating':rating,'recommendation':'Recommended' if rating else 'Not recommended',
                        'sentiment':sentiment,'n':n,'denominator':denominator,
                        'percentage':round(100*n/denominator,2) if denominator else 0})
    return out


def population_ids(conn, rating=None, sentiment=None, related_tag=None, related_sentiment=None):
    """Set semantics: a review qualifies if all independent conditions match."""
    conditions=["r.status='ok'", "EXISTS (SELECT 1 FROM review_tags co WHERE co.review_id=r.id AND co.tag=?)"]
    args=[COOP]
    if sentiment is not None:
        conditions[1] = "EXISTS (SELECT 1 FROM review_tags co WHERE co.review_id=r.id AND co.tag=? AND co.sentiment=?)"
        args.append(sentiment)
    if rating is not None:
        conditions.append('r.rating=?'); args.append(int(rating))
    if related_tag:
        conditions.append('EXISTS (SELECT 1 FROM review_tags extra WHERE extra.review_id=r.id AND extra.tag=?' + (' AND extra.sentiment=?' if related_sentiment else '') + ')')
        args.append(related_tag)
        if related_sentiment: args.append(related_sentiment)
    sql='SELECT r.id FROM reviews r WHERE ' + ' AND '.join(conditions) + ' ORDER BY r.id'
    return [r[0] for r in conn.execute(sql,args)]


def related_comparisons(conn, rating, sentiment, sort='difference', limit=OTHER_TAG_LIMIT):
    """Other-tag sentiment prevalence in selected co-op cohort vs other reviews in SAME rating group.
    Other reviews = same recommendation excluding selected co-op sentiment cohort.
    Positive and negative co-tags are distinct; one review can have both.
    """
    rating=int(rating)
    selected=set(population_ids(conn,rating,sentiment))
    all_same={r[0] for r in conn.execute("SELECT id FROM reviews WHERE status='ok' AND rating=?",(rating,))}
    other=all_same-selected
    if not selected: return []
    rows=conn.execute('''SELECT DISTINCT r.id, t.tag, t.sentiment FROM reviews r
        JOIN review_tags t ON t.review_id=r.id
        WHERE r.status='ok' AND r.rating=? AND t.tag<>? AND t.sentiment IN ('positive','negative')''',(rating,COOP)).fetchall()
    counts={}
    for rid,tag,sent in rows:
        key=(tag,sent)
        if key not in counts: counts[key]=[0,0]
        counts[key][0 if rid in selected else 1]+=1
    out=[]
    for (tag,sent),(a,b) in counts.items():
        pa=a/len(selected); pb=b/len(other) if other else 0
        if a < 3: continue
        out.append(dict(tag=tag,sentiment=sent,n=a,comparison_n=b,
            cohort_n=len(selected),other_n=len(other),pct=round(pa*100,1),
            other_pct=round(pb*100,1),difference=round((pa-pb)*100,1),
            ratio=round(pa/pb,2) if pb else None))
    if sort=='count': out.sort(key=lambda x:(x['n'],abs(x['difference'])), reverse=True)
    elif sort=='relative': out.sort(key=lambda x:(x['ratio'] or 0,x['n']), reverse=True)
    else: out.sort(key=lambda x:(x['difference'],x['n']), reverse=True)
    return out[:limit]


def evidence_quality(conn, review_ids=None):
    sql='''SELECT t.review_id,t.row_id,t.evidence_quote,t.span_start,t.span_end,t.found,r.body
        FROM review_tags t JOIN reviews r ON r.id=t.review_id
        WHERE r.status='ok' AND t.tag=?'''
    rows=conn.execute(sql,(COOP,)).fetchall()
    ids=set(review_ids) if review_ids is not None else None
    valid=0; invalid=0; total=0
    for x in rows:
        if ids is not None and x['review_id'] not in ids: continue
        total+=1
        if exact_span(x['body'],x['span_start'],x['span_end'],x['evidence_quote']):valid+=1
        else:invalid+=1
    return {'total_assignments':total,'exact_spans':valid,'unverified_spans':invalid}


def exact_span(body,start,end,quote):
    return bool(body is not None and quote is not None and isinstance(start,int) and isinstance(end,int)
        and start >=0 and end>start and end<=len(body) and body[start:end]==quote)


def review_page(conn, ids, page=1, per_page=8, search='', order='recent', language='all'):
    ids=set(ids)
    if not ids:return [],0
    # Search within the population, never broaden it.
    items=[]
    for row in conn.execute("SELECT id,date,rating,overall_sentiment,body,playtime_at_review_min,votes_up,original,language FROM reviews WHERE status='ok'"):
        if row['id'] not in ids: continue
        if language!='all' and (row['language'] or 'unknown')!=language: continue
        if search and search.casefold() not in (row['body'] or '').casefold() and search not in row['id']:continue
        items.append(dict(row))
    if order=='helpful':items.sort(key=lambda x:(x['votes_up'] or 0,x['date'] or ''),reverse=True)
    elif order=='oldest':items.sort(key=lambda x:x['date'] or '')
    else:items.sort(key=lambda x:x['date'] or '',reverse=True)
    n=len(items); page=max(1,int(page))
    items=items[(page-1)*per_page:page*per_page]
    for row in items:
        try:row['source_url']=json.loads(row.pop('original') or '{}').get('recommendation_url')
        except (ValueError,TypeError):row['source_url']=None
        row['assignments']=[dict(t) for t in conn.execute('''SELECT row_id,tag,sentiment,reason,evidence_quote,span_start,span_end,found,source,status
            FROM review_tags WHERE review_id=? ORDER BY span_start,row_id''',(row['id'],))]
        for t in row['assignments']:
            t['verified']=exact_span(row['body'],t['span_start'],t['span_end'],t['evidence_quote'])
    return items,n


def manifest(conn,db_path,rating=None,sentiment=None,related_tag=None,related_sentiment=None):
    ids=population_ids(conn,rating,sentiment,related_tag,related_sentiment)
    base=baseline(conn)
    return {'schema_version':'1.0','dataset_sha256':fingerprint(db_path),
      'definition':{'key':'coop_population','primary_tag':COOP,'status':'ok','recommendation_rating':rating,
        'tag_sentiment':sentiment,'related_tag':related_tag,'related_sentiment':related_sentiment,
        'counting_unit':'unique reviews satisfying all conditions'},
      'population':{'n_reviews':len(ids),'review_ids':ids},
      'baseline':base, 'evidence_quality':evidence_quality(conn,ids),
      'notes':['Tag sentiments may overlap in one review.','An evidence span is highlightable only when quote exactly matches the review text at the stored offsets.','Tag co-occurrence does not establish causation.']}


def snapshot(conn, db_path):
    result={'dataset_sha256':fingerprint(db_path),'baseline':baseline(conn),'matrix':matrix(conn)}
    result['comparisons']={f'{r}:{s}':related_comparisons(conn,r,s,limit=50) for r in (1,0) for s in SENTIMENTS}
    return result


def available_languages(conn):
    """Only stored language metadata: no unsupported inference from review text."""
    return [dict(language=(row[0] or 'unknown'), n=row[1]) for row in conn.execute(
        "SELECT language,COUNT(*) FROM reviews WHERE status='ok' GROUP BY language ORDER BY COUNT(*) DESC")]


def puzzle_population_ids(conn,rating=None,issue=None,sentiment='negative',related_tag=None,related_sentiment=None):
    """All puzzle issue definitions are per-review set operations, not tag-assignment counts."""
    if issue is not None and issue not in PUZZLE_ISSUES:
        raise ValueError('Unknown puzzle issue')
    tags=(issue,) if issue else PUZZLE_ISSUES
    placeholders=','.join('?' for _ in tags)
    where=["r.status='ok'",f"EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id=r.id AND t.tag IN ({placeholders}) AND t.sentiment=?)"]
    args=[*tags,sentiment]
    if rating is not None:where.append('r.rating=?');args.append(int(rating))
    if related_tag:
        where.append('EXISTS (SELECT 1 FROM review_tags x WHERE x.review_id=r.id AND x.tag=?' + (' AND x.sentiment=?' if related_sentiment else '') + ')')
        args.append(related_tag)
        if related_sentiment:args.append(related_sentiment)
    return [r[0] for r in conn.execute('SELECT r.id FROM reviews r WHERE '+' AND '.join(where)+' ORDER BY r.id',args)]


def puzzle_matrix(conn, sentiment='negative'):
    """Grouped query avoids repeated full-review scans on startup."""
    grouped={(int(r['rating']),r['tag']):int(r['n']) for r in conn.execute("""
        SELECT r.rating,t.tag,COUNT(DISTINCT r.id) n FROM reviews r
        JOIN review_tags t ON t.review_id=r.id
        WHERE r.status='ok' AND t.sentiment=? AND t.tag IN (?,?,?)
        GROUP BY r.rating,t.tag""",(sentiment,*PUZZLE_ISSUES))}
    totals={int(r[0]):int(r[1]) for r in conn.execute(
        "SELECT rating,COUNT(*) FROM reviews WHERE status='ok' GROUP BY rating")}
    return [dict(rating=rating,issue=issue,n=grouped.get((rating,issue),0),
                 denominator=totals.get(rating,0),
                 percentage=round(100*grouped.get((rating,issue),0)/totals[rating],1) if totals.get(rating) else 0)
            for rating in (1,0) for issue in PUZZLE_ISSUES]


def puzzle_related(conn, rating, issue=None, limit=12, sentiment='negative'):
    """Both positive and negative named-puzzle mentions among selected issue reviews.

    Each tag/sentiment is counted once per review; both may occur in the same
    review, so stacked shares represent mentions rather than an exclusive partition.
    """
    selected=set(puzzle_population_ids(conn,rating,issue,sentiment=sentiment))
    if not selected:return []
    rows=conn.execute("""SELECT DISTINCT r.id,t.tag,t.sentiment FROM reviews r
        JOIN review_tags t ON r.id=t.review_id JOIN tags d ON d.name=t.tag
        WHERE r.status='ok' AND (? IS NULL OR r.rating=?)
          AND t.sentiment IN ('positive','negative') AND d.grp='Puzzles' """,(rating,rating)).fetchall()
    counts={}
    for rid,tag,sent in rows:
        if rid in selected:
            counts.setdefault(tag,{'positive':set(),'negative':set()})[sent].add(rid)
    out=[]
    for tag,c in counts.items():
        pos=len(c['positive']);neg=len(c['negative'])
        out.append(dict(tag=tag,positive_n=pos,negative_n=neg,
                        positive_pct=round(100*pos/len(selected),1),
                        negative_pct=round(100*neg/len(selected),1),
                        population_n=len(selected),total_mentions=pos+neg))
    out.sort(key=lambda x:(-x['total_mentions'],x['tag']))
    return out[:limit]


def puzzle_manifest(conn,db_path,rating=None,issue=None,sentiment='negative'):
    ids=puzzle_population_ids(conn,rating,issue,sentiment=sentiment)
    return {'schema_version':'1.0','dataset_sha256':fingerprint(db_path),
        'definition':{'key':'puzzle_frustration','status':'ok','recommendation_rating':rating,
                      'primary_tags':list(PUZZLE_ISSUES if issue is None else [issue]),
                      'tag_sentiment':sentiment,'counting_unit':'unique reviews satisfying all conditions'},
        'population':{'n_reviews':len(ids),'review_ids':ids},
        'evidence_quality':evidence_quality_for_tags(conn,ids,PUZZLE_ISSUES if issue is None else [issue]),
        'notes':['Tag populations overlap.','All underlying review assignments are preserved.','No causal inference is made.']}


def evidence_quality_for_tags(conn,review_ids,tags):
    ids=set(review_ids);valid=invalid=0
    if not ids:return {'total_assignments':0,'exact_spans':0,'unverified_spans':0}
    placeholders=','.join('?' for _ in tags)
    for t in conn.execute(f"""SELECT t.review_id,t.evidence_quote,t.span_start,t.span_end,r.body
       FROM review_tags t JOIN reviews r ON r.id=t.review_id
       WHERE r.status='ok' AND t.tag IN ({placeholders})""", list(tags)):
        if t['review_id'] not in ids:continue
        if exact_span(t['body'],t['span_start'],t['span_end'],t['evidence_quote']):valid+=1
        else:invalid+=1
    return {'total_assignments':valid+invalid,'exact_spans':valid,'unverified_spans':invalid}


# Named puzzle strengths: a third, independently navigable analytical case.
def named_puzzle_names(conn):
    return [x[0] for x in conn.execute("SELECT name FROM tags WHERE grp='Puzzles' ORDER BY name")]


def named_puzzle_ids(conn, tag=None, sentiment=None, rating=None, related_tag=None, related_sentiment=None):
    names=named_puzzle_names(conn)
    if tag is not None and tag not in names:raise ValueError('Unknown named puzzle')
    tags=[tag] if tag else names
    where=["r.status='ok'",'EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id=r.id AND t.tag IN ('+','.join('?' for _ in tags)+')'+(' AND t.sentiment=?' if sentiment else '')+')']
    args=list(tags)
    if sentiment:args.append(sentiment)
    if rating is not None:where.append('r.rating=?');args.append(int(rating))
    if related_tag:
        where.append('EXISTS (SELECT 1 FROM review_tags t2 WHERE t2.review_id=r.id AND t2.tag=?'+(' AND t2.sentiment=?' if related_sentiment else '')+')')
        args.append(related_tag)
        if related_sentiment:args.append(related_sentiment)
    return [row[0] for row in conn.execute('SELECT r.id FROM reviews r WHERE '+' AND '.join(where)+' ORDER BY r.id',args)]


def named_puzzle_summary(conn):
    """Grouped tag counts avoid repeated per-tag subqueries."""
    grouped={}
    for tag,sentiment,n in conn.execute("""
        SELECT t.tag,t.sentiment,COUNT(DISTINCT t.review_id)
        FROM review_tags t JOIN reviews r ON r.id=t.review_id
        JOIN tags d ON d.name=t.tag
        WHERE r.status='ok' AND d.grp='Puzzles'
        GROUP BY t.tag,t.sentiment"""):
        grouped.setdefault(tag,{})[sentiment]=int(n)
    totals={tag:int(n) for tag,n in conn.execute("""
        SELECT t.tag,COUNT(DISTINCT t.review_id) FROM review_tags t
        JOIN reviews r ON r.id=t.review_id JOIN tags d ON d.name=t.tag
        WHERE r.status='ok' AND d.grp='Puzzles' GROUP BY t.tag""")}
    out=[]
    for tag in named_puzzle_names(conn):
        n=totals.get(tag,0);pos=grouped.get(tag,{}).get('positive',0);neg=grouped.get(tag,{}).get('negative',0)
        out.append(dict(tag=tag,n=n,positive_n=pos,negative_n=neg,
                        positive_pct=round(100*pos/n,1) if n else 0,
                        negative_pct=round(100*neg/n,1) if n else 0))
    return sorted(out,key=lambda x:(-x['positive_n'],x['tag']))


def named_puzzle_related(conn,tag,sentiment,limit=14,rating=None):
    selected=set(named_puzzle_ids(conn,tag,sentiment,rating))
    if not selected:return []
    results=[]
    for t,s,rid in conn.execute("SELECT DISTINCT tag,sentiment,review_id FROM review_tags WHERE sentiment IN ('positive','negative') AND tag<>?",(tag,)):
        if rid in selected: results.append((t,s,rid))
    from collections import defaultdict
    counts=defaultdict(set)
    for t,s,rid in results:counts[t,s].add(rid)
    records=[{'tag':t,'sentiment':sent,'n':len(ids),'pct':round(len(ids)/len(selected)*100,1),'population_n':len(selected)}
             for (t,sent),ids in counts.items() if len(ids)>=2]
    return sorted(records,key=lambda x:(-x['n'],x['tag']))[:limit]


def named_puzzle_manifest(conn,db_path,tag=None,sentiment=None,rating=None):
    ids=named_puzzle_ids(conn,tag,sentiment,rating)
    return {'schema_version':'1.0','dataset_sha256':fingerprint(db_path),
      'definition':{'key':'named_puzzle','tag':tag,'tag_sentiment':sentiment,'recommendation_rating':rating,
                    'counting_unit':'unique reviews satisfying all conditions'},
      'population':{'n_reviews':len(ids),'review_ids':ids},
      'evidence_quality':evidence_quality_for_tags(conn,ids,[tag] if tag else named_puzzle_names(conn))}


# Unexpected: recommendation and overall text sentiment are distinct signals.
def recommended_sentiment_summary(conn, rating=1):
    """Overall text sentiment, per recommendation group (unique analyzed reviews)."""
    counts={r[0] or 'unknown':int(r[1]) for r in conn.execute(
        "SELECT overall_sentiment,COUNT(*) FROM reviews WHERE status='ok' AND rating=? GROUP BY overall_sentiment",(rating,))}
    return [{'sentiment':sent,'n':counts.get(sent,0),'rating':rating} for sent in SENTIMENTS]


def recommended_sentiment_ids(conn,sentiment=None,related_tag=None,related_sentiment=None,rating=1):
    where=["r.status='ok'","r.rating=?"]
    args=[rating]
    if sentiment:
        where.append('r.overall_sentiment=?');args.append(sentiment)
    if related_tag:
        where.append('EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id=r.id AND t.tag=?' +
                     (' AND t.sentiment=?' if related_sentiment else '') + ')')
        args.append(related_tag)
        if related_sentiment:args.append(related_sentiment)
    return [r[0] for r in conn.execute('SELECT r.id FROM reviews r WHERE '+' AND '.join(where)+' ORDER BY r.id',args)]


def recommended_related(conn,sentiment,limit=16,rating=1):
    selected=set(recommended_sentiment_ids(conn,sentiment,rating=rating))
    if not selected:return []
    rows=conn.execute("""SELECT DISTINCT r.id,t.tag,t.sentiment FROM reviews r
      JOIN review_tags t ON t.review_id=r.id WHERE r.status='ok' AND r.rating=?
      AND t.sentiment IN ('positive','negative')""",(rating,))
    counts={}
    for rid,tag,sent in rows:
        if rid in selected:counts.setdefault((tag,sent),set()).add(rid)
    out=[dict(tag=tag,sentiment=sent,n=len(ids),pct=round(100*len(ids)/len(selected),1),population_n=len(selected))
         for (tag,sent),ids in counts.items() if len(ids)>=2]
    return sorted(out,key=lambda x:(-x['n'],x['tag'],x['sentiment']))[:limit]


def recommended_manifest(conn,db_path,sentiment=None,rating=1):
    ids=recommended_sentiment_ids(conn,sentiment,rating=rating)
    return {'schema_version':'1.0','dataset_sha256':fingerprint(db_path),
      'definition':{'key':'recommendation_overall_sentiment','status':'ok','rating':rating,
                    'overall_sentiment':sentiment,'counting_unit':'unique reviews'},
      'population':{'n_reviews':len(ids),'review_ids':ids},
      'evidence_quality':evidence_quality_for_tags(conn,ids,[t[0] for t in conn.execute('SELECT name FROM tags')]),
      'notes':['Overall sentiment is distinct from individual tag sentiment.',
               'Interpretations are stored separately.']}


# Playtime: values are minutes at review time; mutually exclusive bins.
PLAYTIME_BUCKETS=(('Under 1 hour',0,60),('1–3 hours',60,180),('3–6 hours',180,360),
                  ('6–12 hours',360,720),('12–24 hours',720,1440),('24+ hours',1440,None))

def playtime_summary(conn):
    out=[]
    for name,lo,hi in PLAYTIME_BUCKETS:
        condition='playtime_at_review_min >= ?' + (' AND playtime_at_review_min < ?' if hi is not None else '')
        args=[lo]+([hi] if hi is not None else [])
        row=conn.execute('SELECT COUNT(*) n,SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) positive '
            "FROM reviews WHERE status='ok' AND "+condition,args).fetchone()
        n=row['n']; good=row['positive'] or 0
        out.append({'bucket':name,'n':n,'recommended':good,'not_recommended':n-good,
                    'rate':round(100*good/n,1) if n else 0})
    return out


def playtime_ids(conn,bucket=None,rating=None,related_tag=None,related_sentiment=None):
    cond=["r.status='ok'"]
    args=[]
    if bucket is not None:
        matched=next(((lo,hi) for name,lo,hi in PLAYTIME_BUCKETS if name==bucket),None)
        if matched is None:raise ValueError('Invalid playtime bucket')
        lo,hi=matched
        cond.append('r.playtime_at_review_min >= ?');args.append(lo)
        if hi is not None:cond.append('r.playtime_at_review_min < ?');args.append(hi)
    if rating is not None:cond.append('r.rating=?');args.append(int(rating))
    if related_tag:
        cond.append('EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id=r.id AND t.tag=?'+
                    (' AND t.sentiment=?' if related_sentiment else '')+')')
        args.append(related_tag)
        if related_sentiment:args.append(related_sentiment)
    return [r[0] for r in conn.execute('SELECT r.id FROM reviews r WHERE '+' AND '.join(cond)+' ORDER BY r.id',args)]


def playtime_related(conn,bucket,rating=None,limit=18):
    ids=playtime_ids(conn,bucket,rating)
    if not ids:return []
    selected=set(ids)
    counts={}
    for rid,tag,sent in conn.execute("""SELECT DISTINCT t.review_id,t.tag,t.sentiment
        FROM review_tags t JOIN reviews r ON r.id=t.review_id
        WHERE r.status='ok' AND t.sentiment IN ('positive','negative')"""):
        if rid in selected:counts.setdefault((tag,sent),set()).add(rid)
    out=[dict(tag=tag,sentiment=sent,n=len(rids),pct=round(100*len(rids)/len(selected),1),population_n=len(selected))
         for (tag,sent),rids in counts.items()]
    return sorted(out,key=lambda x:(-x['n'],x['tag'],x['sentiment']))[:limit]


def playtime_manifest(conn,db_path,bucket=None,rating=None):
    ids=playtime_ids(conn,bucket,rating)
    return {'schema_version':'1.0','dataset_sha256':fingerprint(db_path),
       'definition':{'key':'playtime_at_review','status':'ok','bucket':bucket,'rating':rating,
                      'bucket_rules':'[lower,upper) minutes; final bucket >=1440','counting_unit':'unique reviews'},
       'population':{'n_reviews':len(ids),'review_ids':ids},
       'evidence_quality':evidence_quality_for_tags(conn,ids,[t[0] for t in conn.execute('SELECT name FROM tags')]),
       'notes':['Playtime at review time is observational, not longitudinal player progression.']}
