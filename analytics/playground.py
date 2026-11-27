"""Reusable, deterministic tag filter, overlap and sentiment-history queries."""
from __future__ import annotations
from collections import defaultdict

SENTIMENTS = ('positive', 'negative', 'neutral', 'mixed')


def all_tags(conn):
    return [r[0] for r in conn.execute('SELECT name FROM tags ORDER BY grp,name')]


def filter_ids(conn, tag=None, sentiments=None, compare_tag=None, compare_sentiments=None):
    """AND between tag filters; OR within each tag's sentiment choices.

    Each returned review is unique even where repeated tag assignments or
    multiple sentiments exist. An empty sentiment choice means any sentiment.
    """
    clauses=["r.status='ok'"]
    args=[]
    for t, choices in ((tag,sentiments),(compare_tag,compare_sentiments)):
        if not t:continue
        sub='EXISTS(SELECT 1 FROM review_tags x WHERE x.review_id=r.id AND x.tag=?'
        args.append(t)
        valid=[s for s in (choices or []) if s in SENTIMENTS]
        if valid:
            sub+=' AND x.sentiment IN ('+','.join('?' for _ in valid)+')'
            args.extend(valid)
        clauses.append(sub+')')
    return [r[0] for r in conn.execute('SELECT r.id FROM reviews r WHERE '+' AND '.join(clauses)+' ORDER BY r.id',args)]


def sentiment_history(conn, tag, ids=None, grain='day'):
    """For each period, total distinct reviews containing tag, and unique
    review/sentiment mentions. Multi-sentiment reviews can count in >1 segment.
    Uses date of review, not review edit date or tag creation date.
    """
    if not tag:return []
    wanted=None if ids is None else set(ids)
    fmt="substr(r.date,1,10)" if grain=='day' else "strftime('%Y-%W',substr(r.date,1,10))"
    sql=f'''SELECT {fmt} period, r.id review_id, t.sentiment sentiment
      FROM reviews r JOIN review_tags t ON t.review_id=r.id
      WHERE r.status='ok' AND t.tag=? AND r.date IS NOT NULL
        AND t.sentiment IN ('positive','negative','neutral','mixed')'''
    groups=defaultdict(lambda:dict(reviews=set(), mentions=defaultdict(set)))
    for r in conn.execute(sql,(tag,)):
        if wanted is not None and r['review_id'] not in wanted:continue
        rec=groups[r['period']]
        rec['reviews'].add(r['review_id'])
        rec['mentions'][r['sentiment']].add(r['review_id'])
    result=[]
    for day,grp in sorted(groups.items()):
        counts={s:len(grp['mentions'].get(s,set())) for s in SENTIMENTS}
        total=sum(counts.values())
        result.append(dict(period=day,n_reviews=len(grp['reviews']),n_sentiment_mentions=total,
                           **counts,**{s+'_share':100*counts[s]/total if total else 0 for s in SENTIMENTS}))
    return result


def technical_named_overlap(conn):
    """For each named puzzle and technical tag, intersect unique reviews with
    negative sentiment on BOTH tags. Return count and denominator (negative
    mentions of that puzzle). No claim that the bug happened in that puzzle.
    """
    technical=('Progression blockers','Bugs & glitches','Crashes & black screens',
               'Save & progress','Multiplayer connectivity','Voice chat')
    named=[r[0] for r in conn.execute("SELECT name FROM tags WHERE grp='Puzzles' ORDER BY name")]
    idx=defaultdict(set)
    for r in conn.execute('''SELECT DISTINCT t.review_id,t.tag FROM review_tags t
       JOIN reviews r ON r.id=t.review_id WHERE r.status='ok' AND t.sentiment='negative' '''):
        idx[r['tag']].add(r['review_id'])
    return [dict(puzzle=p,technical=t,n=len(idx[p]&idx[t]),
                 puzzle_negative_n=len(idx[p]),
                 pct_of_puzzle_negative=round(100*len(idx[p]&idx[t])/len(idx[p]),1) if idx[p] else 0,
                 ids=sorted(idx[p]&idx[t])) for p in named for t in technical]
