"""Shared score and event rules for every rating built from pool-data (Aleksandrs, 22-23 Nov 2026).

One copy for all builds: the builds download this file (get_data.sh) and import it, so a rule fixed here reaches every rating.
Pure Python, no other files needed.

Use:
    import score_rules as SR
    SR.name_handicap(name, organizer, date) -> reason or None  (handicap by name or known organizer rule)
    rules = SR.ScoreRules(events, format_ok)
        events: {event_id: {'name': str, 'per_match_race': bool,
                            'matches': [(match_id, round_name, stored_race, (score_a, score_b)), ...]}}
                Only matches the build would count otherwise (valid scores, race 3+, no straight pool), from events not
                already excluded. per_match_race: True when the platform stores a reliable race for each match
                (Tournament Service), False when it stores one race for the whole event (CueScore).
        format_ok: event ids checked by hand and kept, whatever the odd-format check says.
    rules.odd_events                       -> {event_id: reason}   events not counted
    rules.decide(event_id, match_id, round_name, stored_race, score)
                                           -> (action, score, race, how)
        action: 'keep' (as recorded), 'fix' (score raised to the race), 'walkover' (not counted), 'short' (kept, listed)

The race of a match is the race its round was actually played to: the most common winner score in the round (ties: the
shorter). Rounds are split by stored race where the platform stores it per match. A round of 2 matches: the other match (if it
went longer); a final of one match: the semifinals; another single match only when x:0 (the other small rounds, then the whole
event). A stored race is used only when trusted: always where stored per match; otherwise only when the organizer set that
round's race apart from the event's usual one and bigger rounds with that race reached it. Third-place matches count as recorded.
    winner reached the race: as recorded
    x:0 one short (3:0 in a race to 4): counted as the full race (4:0)
    x:0 two or more short (3:0 in a race to 5): walkover written as a score, not counted
    one short with racks for both (4:1 in a race to 5): counted as the full race (5:1)
    two or more short with racks for both: as recorded, listed for checking
Events not counted: a test or money game of one match; events where in at least 2 rounds (and 40% of rounds) the winners stop
at different numbers; many drawn matches; rounds mixing short matches with matches over twice as long (handicap or fixed racks).
"""
import collections
import re

# Event names that mean handicap: Baribal Monday events (Baribali Esmaspäevak in all spellings, also Barica/Barika), Baribal HC,
# and 'fora' (handicap in Lithuanian, Russian фора). Baribal Estonia-Finland events are not handicap.
HANDICAP_NAME = re.compile(r'bari(?:bal|[ck]a)\w*\s+(?:suvine\s+)?esma\w*|baribal\w*\s+hc\b|\bfora\b|фора', re.I)
THIRD_PLACE = re.compile(r'3rd|third|bronz|3\.? ?(?:vieta|koht|place)|treči|kolmand|trešā', re.I)
SEMI = re.compile(r'semi|pusfin|pusfināl|pusfinal|poolfin|1/2', re.I)
FINAL = re.compile(r'^\s*(final|finals|fināls|finalas|finaal|finale)\s*$', re.I)
TEST_OR_MONEY = re.compile(r'test|money', re.I)


# Events known to be played with handicap although CueScore does not say so in its data (Aleksandrs 23 Nov 2026):
# every Monday event of Hill Hill Billiard Cafe (Tallinn) since 2019.
HILL_HILL = re.compile(r'hill\s*hill', re.I)


def name_handicap(name, organizer='', date=None):
    """Reason if the event is handicap by its name or by a known organizer rule, else None. date: datetime.date (optional)."""
    if HANDICAP_NAME.search(name or ''): return 'handicap (Baribal Monday, Baribal HC or "fora" in the name)'
    if date is not None and date.weekday() == 0 and (HILL_HILL.search(organizer or '') or HILL_HILL.search(name or '')):
        return 'handicap (Hill Hill Monday event)'
    return None


def _mode(c):
    top = max(c.values())
    return min(k for k, v in c.items() if v == top)


def _race(v):
    return int(v) if str(v).isdigit() and int(v) > 0 else 0


class ScoreRules:
    def __init__(self, events, format_ok=()):
        self.events = events
        fok = {str(k) for k in format_ok}
        self.odd_events = {}
        for eid, e in events.items():
            if str(eid) in fok: continue
            why = self._odd(e)
            if why: self.odd_events[eid] = why
        self.round_w = collections.defaultdict(collections.Counter)
        self.round_sc = collections.defaultdict(list)
        self.small_w = collections.defaultdict(collections.Counter)
        self.event_w = collections.defaultdict(collections.Counter)
        self.semi_w = collections.defaultdict(collections.Counter)
        self.own_w = collections.defaultdict(collections.Counter)
        self.stored_mode = {}
        for eid, e in events.items():
            if eid in self.odd_events: continue
            for mid, rnd, st, sc in e['matches']:
                k = self._rkey(eid, rnd, st)
                self.round_w[k][max(sc)] += 1
                self.round_sc[k].append((mid, max(sc)))
        for eid, e in events.items():
            if eid in self.odd_events: continue
            for mid, rnd, st, sc in e['matches']:
                k = self._ekey(eid, st)
                n = sum(self.round_w[self._rkey(eid, rnd, st)].values())
                self.event_w[k][max(sc)] += 1
                if n < 3 and not THIRD_PLACE.search(rnd or ''): self.small_w[k][max(sc)] += 1
                if SEMI.search(rnd or ''): self.semi_w[k][max(sc)] += 1
                if n >= 3 and _race(st): self.own_w[(eid, _race(st))][max(sc)] += 1
            c = collections.Counter(_race(st) for _, _, st, _ in e['matches'] if _race(st))
            if c: self.stored_mode[eid] = _mode(c)

    def _per_match(self, eid):
        return self.events[eid].get('per_match_race', False)

    def _rkey(self, eid, rnd, st):
        return (eid, rnd, _race(st)) if self._per_match(eid) else (eid, rnd)

    def _ekey(self, eid, st):
        return (eid, _race(st)) if self._per_match(eid) else eid

    def _odd(self, e):
        ms = e['matches']
        if not ms: return None
        if len(ms) == 1:   # often the only race to 3+ of an event, or a real two-player event: counts unless test or money
            return 'test or money game, one match' if TEST_OR_MONEY.search(e.get('name') or '') else None
        em = _mode(collections.Counter(max(sc) for *_, sc in ms))
        rounds = collections.defaultdict(list)
        for mid, rnd, st, sc in ms:
            rounds[(rnd, _race(st)) if e.get('per_match_race') else rnd].append(sc)
        mixed = rounds_n = huge = 0
        for scs in rounds.values():
            ws = [max(s) for s in scs]
            if len(scs) >= 2 and max(ws) > 2 * min(ws) and max(ws) > 2 * em: huge += 1
            wp = [max(s) for s in scs if min(s) > 0 and s[0] != s[1]]   # walkover-like x:0 and draws left out
            if len(wp) < 2: continue
            rounds_n += 1
            mixed += len(set(wp)) > 1
        ties = sum(1 for *_, s in ms if s[0] == s[1])
        why = []
        if mixed >= 2 and mixed >= 0.4 * rounds_n: why.append(f'in {mixed} of {rounds_n} rounds the winners stop at different numbers')
        if ties >= 3 and ties >= 0.15 * len(ms): why.append(f'{ties} of {len(ms)} matches drawn')
        if huge: why.append(f'{huge} round(s) mixing short matches with matches over twice as long')
        return 'odd format (looks like handicap or fixed racks): ' + '; '.join(why) if why else None

    def _trusted(self, eid, st):
        o = _race(st)
        if not o: return 0
        if self._per_match(eid): return o
        if o == self.stored_mode.get(eid): return 0   # a race left at the event's default proves nothing
        c = self.own_w[(eid, o)]
        return o if sum(c.values()) >= 3 and _mode(c) == o else 0

    def race_of(self, eid, mid, rnd, st, sc):
        rk = self._rkey(eid, rnd, st)
        rw = self.round_w[rk]
        n = sum(rw.values())
        if n >= 3: return _mode(rw), f'round of {n} matches'
        k = self._ekey(eid, st)
        tr = self._trusted(eid, st)
        if n == 2:
            other = [w for m, w in self.round_sc[rk] if m != mid]
            if other and other[0] > max(sc): return other[0], 'other match of the round'
            if tr and max(sc) < tr and (not other or other[0] < tr): return tr, 'stored race (both matches of the round short of it)'
            return None, 'other match of the round'
        if FINAL.search(rnd or '') and self.semi_w[k]: return _mode(self.semi_w[k]), 'semifinals'
        if tr and max(sc) < tr: return tr, 'stored race'
        if min(sc) > 0: return None, 'single match, kept'
        if sum(self.small_w[k].values()) >= 3: return _mode(self.small_w[k]), f'small rounds together ({sum(self.small_w[k].values())} matches)'
        if sum(self.event_w[k].values()) >= 3: return _mode(self.event_w[k]), f'whole event ({sum(self.event_w[k].values())} matches)'
        return (_race(st) or None), 'stored race'

    def decide(self, eid, mid, rnd, st, sc):
        if THIRD_PLACE.search(rnd or ''): return 'keep', sc, None, 'third-place match'
        race, how = self.race_of(eid, mid, rnd, st, sc)
        w, l = max(sc), min(sc)
        if not race or w >= race or w <= l: return 'keep', sc, race, how
        if w == race - 1: return 'fix', ((race, sc[1]) if sc[0] > sc[1] else (sc[0], race)), race, how
        if l == 0: return 'walkover', sc, race, how
        return 'short', sc, race, how
