"""German Pool Rating: collect German CueScore tournaments into data/cuescore_raw.json.

Everything is stored (decided 3 Nov 2026: gather first, decide later): every pool event held in Germany
(all disciplines, singles, doubles, handicap, any race length), every match with a result, walkovers included.
build_db.py decides what counts. Team events (league match days, CueScore type 1) are collected by collect_team.py.

First run (no 'raw_done' flag): lists every month since 2016 (one list query stops at about 9,900 results)
and fetches every pool event. Later runs: every event that started in the last DAYS days, plus new ones.
Usage: python3 collect_cuescore.py [--days 90]
"""
import json, re, sys, time, datetime, html, os, calendar
import requests
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # runs with python -I
import cs_regions as R   # CS_REGION: several countries in one file (13 Nov 2026)

FILE = (os.environ.get('CS_FILE') or 'data/de_cuescore_raw.json.gz')   # gzipped: the GitHub website accepts at most 25 MB per uploaded file
DAYS = int(sys.argv[sys.argv.index('--days') + 1]) if '--days' in sys.argv else 14   # 90 until 13 Nov 2026 (load on CueScore)
DELAY = 1.0   # seconds between requests, one request at a time (13 Nov 2026: was 6 in parallel)
TODAY = datetime.date.today()
CUTOFF = TODAY - datetime.timedelta(days=DAYS)
COUNTRY = (os.environ.get('CS_COUNTRY') or 'Germany')   # set per country by cuescore.yml
FIRST_YEAR = 2016
API = 'https://api.cuescore.com'
S = requests.Session(); S.headers.update({'User-Agent': 'Mozilla/5.0 (pool rating updater)', 'Accept-Language': 'en-US,en;q=0.9'})
POOL = re.compile(r'^(8|9|10)-Ball$|^Straightpool$', re.I)   # Aleksandrs 13 Nov 2026: only 8/9/10-ball and straight pool are gathered (before: also 7-ball, Multiball, One pocket, Bank pool, Portuguese 8-ball)

def get(url):
    for i in range(4):
        try:
            time.sleep(DELAY)
            r = S.get(url, timeout=60); r.raise_for_status(); return r
        except Exception:
            if i == 3: raise
            time.sleep(3 * (i + 1))

log = []
def say(*a):
    msg = ' '.join(str(x) for x in a); print(msg, flush=True); log.append(msg)

import gzip
OPEN = (lambda f, m: gzip.open(f, m + 't', encoding='utf-8')) if FILE.endswith('.gz') else (lambda f, m: open(f, m, encoding='utf-8'))
cs = json.load(OPEN(FILE, 'r')) if os.path.exists(FILE) else {'tournaments': [], 'matches': [], 'players': {}}
have = {t[0] for t in cs['tournaments']}
STATUS = {t[0]: (t[14] if len(t) > 14 else '') for t in cs['tournaments']}   # status when stored

CTRY = {}   # tournament id -> listed country (regions)
def cs_list(a, b):
    if R.REGION:
        for c in COUNTRIES:
            for it in R.list_events(get, c, a, b): CTRY[it['tournamentId']] = c; yield it
        return
    off = 0
    while True:
        j = get(f'{API}/tournaments/?country={COUNTRY}&from={a}&to={b}&offset={off}').json()
        for it in j['items']: yield it
        if not j.get('hasMore'): break
        off = j['nextOffset']

def handicap(j):
    h = j.get('handicap')
    if h and (len(h) > 0 if isinstance(h, (list, dict)) else True): return 1
    desc = html.unescape(re.sub(r'<[^>]+>', ' ', j.get('description') or ''))
    return 1 if re.search(r'handi|hcp|hendi|vorgabe', desc, re.I) else 0

def fetch(tid):
    """Tournament row:
    [id, name, start date, discipline, default race, default best-of-sets, handicap 1/0, type, city, owner, matches listed,
     matches stored, country (lower case), venue/club, status, stop date]
    Match row: [tournament id, match id, player A, player B, score A, score B, race, date, round, penalty, game, best-of-sets, match status]
    Player row: [first name, last name, flag (alpha3), club or country represented, lives in, date of the event the club is from]"""
    j = get(f'{API}/tournament/?id={tid}').json()
    tday = (j.get('starttime') or '')[:10]   # event date: which club a player represented most recently
    ms, nm = [], 0
    for m in j.get('matches') or []:
        nm += 1
        a, b = m.get('playerA') or {}, m.get('playerB') or {}
        if not a.get('playerId') or not b.get('playerId'): continue
        if m.get('matchstatus') not in ('finished', 'playing'): continue
        try: sa, sb = int(m['scoreA']), int(m['scoreB'])
        except Exception: continue
        for p in (a, b):
            pid = str(p['playerId'])
            rep = p.get('represents'); club = (rep.get('alpha3') or rep.get('name')) if isinstance(rep, dict) else ''
            if pid not in cs['players']:
                cc = (p.get('country') or {}).get('alpha3', '') if isinstance(p.get('country'), dict) else ''
                lv = p.get('livesIn')
                cs['players'][pid] = [p.get('firstname'), p.get('lastname'), cc, club,
                                      (lv.get('alpha3') or lv.get('name')) if isinstance(lv, dict) else '', tday]
            else:
                # 22 Nov 2026 (Estonian rating, club filter): keep the club from the newest event the player played in
                row = cs['players'][pid]
                if len(row) < 6: row.append('')
                if club and tday and tday >= (row[5] or ''): row[3] = club; row[5] = tday
        ms.append([j['tournamentId'], m['matchId'], a['playerId'], b['playerId'], sa, sb, m.get('raceTo') or 0,
                   (m.get('stoptime') or m.get('starttime') or '')[:10], m.get('roundName') or '', m.get('penalty') or 0,
                   m.get('discipline') or '', m.get('bestOfSets') or 0, m.get('matchstatus') or ''])
    v = (j.get('venues') or [{}])[0] or {}
    trow = [j['tournamentId'], j['name'], (j.get('starttime') or '')[:10], j.get('discipline'), j.get('defaultRaceTo'),
            j.get('defaultBestOfSets'), handicap(j), j.get('type'), v.get('placename') or v.get('city') or '',
            (j.get('owner') or {}).get('name', ''), nm, len(ms), R.event_country(j, CTRY.get(tid) or R.REGION) if R.REGION else COUNTRY.lower(), v.get('name') or '', j.get('status') or '',
            (j.get('stoptime') or '')[:10]]
    return trow, ms

def wanted(it):
    return it.get('status') in ('Finished', 'Active') and it.get('type') != 1 and (R.DISC or POOL).match(it.get('discipline') or '')

def run(tids, threads=1):
    def one(tid):
        for i in range(3):
            try: return tid, fetch(tid)
            except Exception: time.sleep(5)
        return tid, None
    with ThreadPoolExecutor(threads) as ex: res = list(ex.map(one, tids))
    new = upd = 0
    for tid, r in res:
        if not r: say(f'  could not read CueScore {tid}'); continue
        trow, ms = r
        cs['matches'] = [m for m in cs['matches'] if m[0] != tid] + ms
        cs['tournaments'] = [t for t in cs['tournaments'] if t[0] != tid] + [trow]
        if tid in have: upd += 1
        else: new += 1
        have.add(tid)
    return new, upd

def save():
    with OPEN(FILE + '.tmp', 'w') as f: json.dump(cs, f, ensure_ascii=False, separators=(',', ':'))
    os.replace(FILE + '.tmp', FILE)

def backfill_region():
    """One-time, regions: every pool event since FIRST_YEAR, one country and year at a time, saved after each,
    so a first run cut off by the time limit continues where it stopped (cs['listed'] remembers finished country-years)."""
    if cs.get('raw_done'): return
    listed = set(cs.setdefault('listed', []))
    for c in COUNTRIES:
        for y in range(FIRST_YEAR, TODAY.year + 1):
            key = f'{c}:{y}'
            if key in listed: continue
            items = R.list_events(get, c, f'{y}-01-01', f'{y}-12-31')
            for it in items: CTRY[it['tournamentId']] = c
            todo = sorted({it['tournamentId'] for it in items if wanted(it)} - have)
            for k in range(0, len(todo), 300):
                run(todo[k:k + 300]); save()
            if todo: say(f'  {c} {y}: {len(todo)} events')
            cs['listed'].append(key); listed.add(key); save()
    cs['raw_done'] = True

def backfill():
    """One-time: every German pool event since FIRST_YEAR, everything stored (re-reads events stored by the older, filtering collector)."""
    if cs.get('raw_done'): return
    todo = []
    for y in range(FIRST_YEAR, TODAY.year + 1):
        for mth in range(1, 13):
            if datetime.date(y, mth, 1) > TODAY: break
            last = calendar.monthrange(y, mth)[1]
            todo += [it['tournamentId'] for it in cs_list(f'{y}-{mth:02d}-01', f'{y}-{mth:02d}-{last}') if wanted(it)]
    todo = sorted(set(todo) - have)   # events already stored are skipped, so a first run cut off by a time limit continues next time
    say(f'CueScore raw backfill: {len(todo)} {COUNTRY} pool events to read')
    for k in range(0, len(todo), 300):
        run(todo[k:k + 300]); save()
        say(f'  {min(k + 300, len(todo))}/{len(todo)}')
    cs['raw_done'] = True

def update():
    todo = []
    for it in cs_list((TODAY - datetime.timedelta(days=90)).isoformat(), TODAY.isoformat()):
        if not wanted(it): continue
        st = (it.get('starttime') or '')[:10]
        # re-read: new events, events of the last DAYS days, and events of the last 90 days not finished when stored
        if it['tournamentId'] in have and st and st < CUTOFF.isoformat() and \
           (st < (TODAY - datetime.timedelta(days=90)).isoformat() or STATUS.get(it['tournamentId']) == 'Finished'): continue
        todo.append(it['tournamentId'])
    new, upd = run(todo)
    say(f'CueScore: {new} new events, {upd} recent ones re-read')

BPL = r'baltic pool (league|tour)'
def player_sweep():
    """Baltic countries (23 Nov 2026): events whose organizer has no country (e.g. Baltic Billiards Development Union, which runs
    the BPL) and events without a venue country never show in the country listing. Like the Latvian collector: read the profile
    pages of players active here in the last 90 days (each shows the player's latest events) and add unknown pool events held in
    this country, without a country, or BPL events; BPL sister divisions are found through the event page."""
    if COUNTRY not in ('Estonia', 'Latvia', 'Lithuania'): return
    recent = (TODAY - datetime.timedelta(days=90)).isoformat()
    rt = {t[0] for t in cs['tournaments'] if (t[2] or '') >= recent}
    pids = sorted({str(p) for m in cs['matches'] if m[0] in rt for p in (m[2], m[3])})
    checked = set(cs.setdefault('checked', []))
    def page(u):
        for i in range(2):
            try: return requests.get(u, timeout=40, headers={'User-Agent': 'Mozilla/5.0'}).text
            except Exception: time.sleep(3)
        return ''
    with ThreadPoolExecutor(8) as ex: pages = list(ex.map(page, [f'https://cuescore.com/player/x/{p}' for p in pids]))
    queue = sorted({int(x) for h in pages for x in re.findall(r'/tournament/[^"]*?/(\d+)"', h)} - have - checked)
    seen, add = set(), []
    while queue:
        tid = queue.pop(0)
        if tid in seen: continue
        seen.add(tid)
        try: j = get(f'{API}/tournament/?id={tid}').json()
        except Exception: continue
        if j.get('status') != 'Finished': continue   # not finished: looked at again next time
        name = j.get('name') or ''
        v = (j.get('venues') or [{}])[0] or {}
        vc = v.get('country'); vc = ((vc.get('name') if isinstance(vc, dict) else vc) or '').lower()
        oc = (j.get('owner') or {}).get('country'); oc = ((oc.get('name') if isinstance(oc, dict) else oc) or '').lower()
        bpl = bool(re.search(BPL, name, re.I))
        if bpl:
            h = page(f'https://cuescore.com/tournament/x/{tid}')
            queue += [int(i) for sl, i in re.findall(r'/tournament/([^"/]*)/(\d+)"', h) if re.search(BPL, sl.replace('+', ' '), re.I) and int(i) not in have and int(i) not in seen]
        mine = vc == COUNTRY.lower() or (vc == '' and oc in ('', COUNTRY.lower())) or (bpl and vc in ('', COUNTRY.lower()))
        if mine and POOL.match(j.get('discipline') or ''): add.append(tid)
        else: cs['checked'].append(tid)
    new, upd = run(add, 4) if add else (0, 0)
    say(f'CueScore player pages ({COUNTRY}): {len(pids)} players, {len(seen)} unknown events looked at, {new} added')

if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    COUNTRIES = R.countries(get, 'Germany')
    if R.REGION:
        say(f'Region {R.REGION}: {len(COUNTRIES)} countries'); backfill_region()
    else: backfill()
    update()
    try: player_sweep()
    except Exception as e: say(f'player sweep failed: {e}')
    save()
    open('update_log.txt', 'a').write('\n'.join(log) + '\n')
