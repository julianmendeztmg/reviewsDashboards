"""Reusable, deterministic review populations for candidate findings."""
from collections import defaultdict
from .engine import fingerprint, evidence_quality_for_tags

CASES = {
 'presentation': {'title':'Why are visuals praised more than story and atmosphere?', 'chapter':1,
    'description':'Separate positive and negative reactions to visual design, story and atmosphere, and audio.',
    'tags':['Graphics & art direction','Story & atmosphere','Audio & music'],
    'focus':['Graphics & art direction','Story & atmosphere']},
 'technical': {'title':'Which technical problems stop players from progressing?', 'chapter':2,
    'description':'Explore bugs, crashes, save issues and progression blockers by recommendation and tag sentiment.',
    'tags':['Progression blockers','Bugs & glitches','Crashes & black screens','Save & progress','Multiplayer connectivity','Voice chat'],
    'focus':['Progression blockers','Bugs & glitches','Save & progress']},
 'fandom': {'title':'Why do series fans praise the franchise but reject this game?', 'chapter':2,
    'description':'Compare franchise anticipation and comparisons with earlier entries. Explore both positive and negative tag sentiments inside each recommendation group.',
    'tags':['Anticipation & fandom','Series comparison','Co-op experience','Puzzle & level design','Story & atmosphere'],
    'focus':['Anticipation & fandom','Series comparison']},
 'motion': {'title':'Why do some players report discomfort even when they recommend the game?', 'chapter':3,
    'description':'See how motion-sickness mentions differ by recommendation, then explore navigation, abilities and action-related complaints in the same reviews.',
    'tags':['Motion sickness','Map size, walk & navigation','Abilities','Platforming & action elements','Accessibility'],
    'focus':['Motion sickness','Map size, walk & navigation']},
 'launch': {'title':'What changed between October 20 and October 25?', 'chapter':3,
    'description':'First inspect recommendation rates, then compare playtime and sentiment topics on the two dates.',
    'tags':[], 'focus':[]}
}


def candidate_ids(conn,case, rating=None, tag=None, sentiment=None, related_tag=None, related_sentiment=None, day=None):
    if case not in CASES: raise ValueError(case)
    conditions=["r.status='ok'"];args=[]
    if rating is not None: conditions.append('r.rating=?');args.append(int(rating))
    if case=='launch':
        if day:
            conditions.append('substr(r.date,1,10)=?');args.append(day)
        else:
            conditions.append("substr(r.date,1,10) BETWEEN '2026-10-20' AND '2026-11-08'")
    else:
        tags=CASES[case]['tags']
        if tag and tag not in tags: raise ValueError('Tag outside the candidate')
        permitted=[tag] if tag else tags
        marks=','.join('?' for _ in permitted)
        sub=f'EXISTS (SELECT 1 FROM review_tags t WHERE t.review_id=r.id AND t.tag IN ({marks})'
        args.extend(permitted)
        if sentiment: sub+=' AND t.sentiment=?';args.append(sentiment)
        conditions.append(sub+')')
    if related_tag:
        sub='EXISTS(SELECT 1 FROM review_tags z WHERE z.review_id=r.id AND z.tag=?'
        args.append(related_tag)
        if related_sentiment:sub+=' AND z.sentiment=?';args.append(related_sentiment)
        conditions.append(sub+')')
    sql='SELECT r.id FROM reviews r WHERE '+' AND '.join(conditions)+' ORDER BY r.id'
    return [row[0] for row in conn.execute(sql,args)]


def summary(conn,case):
    if case=='launch':
        return [dict(x) for x in conn.execute("""SELECT substr(date,1,10) day,COUNT(*) n,SUM(rating=1) recommended,
          ROUND(100.0*SUM(rating=1)/COUNT(*),1) pct,ROUND(AVG(playtime_at_review_min)/60.0,1) avg_hours
          FROM reviews WHERE status='ok' AND substr(date,1,10) BETWEEN '2026-10-20' AND '2026-11-08'
          GROUP BY day ORDER BY day""")]
    tags=CASES[case]['tags']
    marks=','.join('?' for _ in tags)
    rows=conn.execute(f"""SELECT t.tag,t.sentiment,r.rating,COUNT(DISTINCT r.id) n FROM review_tags t
       JOIN reviews r ON r.id=t.review_id WHERE r.status='ok' AND t.tag IN ({marks})
       AND t.sentiment IN ('positive','negative','mixed','neutral')
       GROUP BY t.tag,t.sentiment,r.rating""",tags).fetchall()
    return [dict(x) for x in rows]


def related(conn,case,ids,limit=18):
    ids=set(ids)
    if not ids:return []
    # Do not include unrelated outside-population records; a review contributes once per tag/sentiment.
    observed=defaultdict(set)
    for row in conn.execute("""SELECT DISTINCT t.review_id,t.tag,t.sentiment FROM review_tags t
       JOIN reviews r ON r.id=t.review_id WHERE r.status='ok' AND t.sentiment IN ('positive','negative')"""):
        if row['review_id'] in ids:observed[(row['tag'],row['sentiment'])].add(row['review_id'])
    out=[dict(tag=tag,sentiment=sent,n=len(matching),pct=round(100*len(matching)/len(ids),1),population_n=len(ids))
         for (tag,sent),matching in observed.items() if len(matching)>=2]
    out.sort(key=lambda x:(x['n'],x['tag']),reverse=True)
    return out[:limit]


def launch_comparison(conn):
    records=[]
    for day in ('2026-10-20','2026-10-25'):
        ids=candidate_ids(conn,'launch',day=day)
        row=conn.execute("""SELECT COUNT(*) n, SUM(rating=1) rec, ROUND(AVG(playtime_at_review_min)/60.0,2) avg_hours
          FROM reviews WHERE status='ok' AND substr(date,1,10)=?""",(day,)).fetchone()
        # Top sentiment-specific complaints, with consistent day-level denominators.
        row2=conn.execute("""SELECT tag, COUNT(DISTINCT t.review_id) n FROM review_tags t
          JOIN reviews r ON r.id=t.review_id WHERE r.status='ok' AND substr(r.date,1,10)=?
          AND t.sentiment='negative' GROUP BY tag ORDER BY n DESC""",(day,)).fetchall()
        records.append({'day':day,'n':row['n'],'recommended':row['rec'],'recommendation_rate':round(100*row['rec']/row['n'],1),
                        'average_playtime_hours':row['avg_hours'],'negative_tags':{x['tag']:x['n'] for x in row2}})
    return records


def candidate_manifest(conn,path,case,**filters):
    ids=candidate_ids(conn,case,**filters)
    tags=CASES[case]['tags'] if case!='launch' else [x[0] for x in conn.execute('SELECT name FROM tags')]
    return {'schema_version':'1.0','case':case,'dataset_sha256':fingerprint(path),
      'definition':{'case':case,'status':'ok','counting_unit':'unique reviews',**filters},
      'population':{'n_reviews':len(ids),'review_ids':ids},
      'evidence_quality':evidence_quality_for_tags(conn,ids,tags),
      'notes':['Tag presence and tag sentiment are distinct.','Co-mentions do not prove causation.','Interpretations are separate and may require editorial refresh.']}
