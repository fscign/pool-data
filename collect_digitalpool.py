"""DigitalPool (digitalpool.com): matches of chosen players only (now: Estonian players). Added 27 Nov 2026.

DigitalPool keeps its results in a GraphQL API (api-nyc.digitalpool.com/v1/graphql, answers without a login). We read
only public result fields (names, flags, scores, races, rounds, tournament name/date/game/venue) and never personal fields.
Requests are slow (one every 3 s) and few: a full read once, then only tournaments of the last 60 days.

Who is searched: data/digitalpool_search.json
  countries: player flags to take (e.g. EE, EST, Estonia)
  names: [full name, first-name pattern, surname pattern]; '_' stands for one letter with an accent (Mägi -> M_gi)

Output data/digitalpool_raw.json.gz:
  tournaments: {id: [name, start date, game_type, tournament_type, venue name, venue country, is_test, handicap_format]}
  matches:     {bracket id: [tournament id, round, match no, name 1, flag 1, score 1, race 1, forfeit 1,
                             name 2, flag 2, score 2, race 2, forfeit 2, bye, status, start date]}
  full_read: date of the last full read
Everything is stored (tests, team events, one pocket...); the rating decides what counts.
"""
import json, gzip, os, sys, time, datetime
import requests

FILE = 'data/digitalpool_raw.json.gz'
API = 'https://api-nyc.digitalpool.com/v1/graphql'
DELAY = 3
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating collector; contact via github.com/fscign/pool-data)',
                                          'content-type': 'application/json'})
SEARCH = json.load(open('data/digitalpool_search.json', encoding='utf-8'))
D = json.load(gzip.open(FILE, 'rt', encoding='utf-8')) if os.path.exists(FILE) else {'tournaments': {}, 'matches': {}, 'full_read': ''}
full = '--full' in sys.argv or not D.get('full_read')
since = None if full else (datetime.date.today() - datetime.timedelta(days=60)).isoformat()

FIELDS = '''id round match_number challenger1_name challenger2_name challenger1_country challenger2_country
 challenger1_score challenger2_score challenger1_race_to challenger2_race_to challenger1_is_forfeit challenger2_is_forfeit
 is_bye status start_time tournament_id
 tournament { id name game_type start_date_time is_test tournament_type handicap_format venue { name country } }'''


def query(where):
    if since: where = {'_and': [where, {'tournament': {'start_date_time': {'_gte': since}}}]}
    body = json.dumps({'query': 'query($w: tournament_brackets_bool_exp!) { tournament_brackets(where: $w) { %s } }' % FIELDS,
                       'variables': {'w': where}})
    for i in range(4):
        try:
            r = S.post(API, data=body, timeout=180); r.raise_for_status(); j = r.json()
            if 'errors' in j: raise RuntimeError(str(j['errors'])[:300])
            return j['data']['tournament_brackets']
        except Exception as e:
            if i == 3: raise
            print('retry', e); time.sleep(10 * (i + 1))


def keep(rows):
    n = 0
    for m in rows:
        t = m['tournament'] or {}; v = t.get('venue') or {}
        D['tournaments'][str(t.get('id'))] = [t.get('name'), (t.get('start_date_time') or '')[:10], t.get('game_type'),
                                              t.get('tournament_type'), v.get('name'), v.get('country'), t.get('is_test'), t.get('handicap_format')]
        new = [m['tournament_id'], m['round'], m['match_number'],
               m['challenger1_name'], m['challenger1_country'], m['challenger1_score'], m['challenger1_race_to'], bool(m['challenger1_is_forfeit']),
               m['challenger2_name'], m['challenger2_country'], m['challenger2_score'], m['challenger2_race_to'], bool(m['challenger2_is_forfeit']),
               bool(m['is_bye']), m['status'], (m['start_time'] or '')[:10]]
        if D['matches'].get(str(m['id'])) != new: n += 1
        D['matches'][str(m['id'])] = new
    return n


def save():
    with gzip.open(FILE + '.tmp', 'wt', encoding='utf-8') as f: json.dump(D, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(FILE + '.tmp', FILE)


C = SEARCH['countries']
changed = keep(query({'_or': [{'challenger1_country': {'_in': C}}, {'challenger2_country': {'_in': C}}]})); time.sleep(DELAY)
for full_name, first, last in SEARCH['names']:
    pats = [f'%{first}%{last}%', f'%{last}%{first}%']
    w = {'_or': [{f'challenger{k}_name': {'_ilike': p}} for p in pats for k in (1, 2)]}
    changed += keep(query(w)); time.sleep(DELAY)
if full: D['full_read'] = datetime.date.today().isoformat()
save()
print(f"{'full' if full else 'last 60 days'}: {changed} new or changed matches; {len(D['matches'])} matches in {len(D['tournaments'])} tournaments")
