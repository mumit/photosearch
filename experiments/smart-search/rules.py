"""Keyword rules for the smart search box's five questions, written before the labelled searches were.
Each returns the same answer names as smartbox.JEV_QUESTIONS."""
import re

I = re.I


def kind(q):
    if re.search(r"\b(only|just) (the )?(photos?|pictures?|pics?|stills?)\b|\bno (videos?|clips?)\b", q, I):
        return "photo"
    if re.search(r"\b(only|just) (the )?(videos?|clips?)\b|\bno (photos?|pictures?|pics?)\b", q, I):
        return "video"
    q2 = re.sub(r"\bvideo ?games?\b|\bmovie (night|theat(er|re)|poster|tickets?)\b|\bat the movies\b", "", q, flags=I)
    if re.search(r"\b(videos?|vids?|clips?|footage|movies?|filmed|filming|recordings?|recorded)\b", q2, I):
        return "video"
    return "either"


def season(q):
    for s, pat in (("spring", r"\bspring(time)?\b(?! (roll|water|onion))"), ("summer", r"\bsummer(time|s)?\b"),
                   ("autumn", r"\bautumn\b|\bfall\b(?! (down|over|off|asleep))"), ("winter", r"\bwinter(time|s)?\b")):
        if re.search(pat, q, I):
            return s
    return "none"


def when(q):
    if re.search(r"\bthis year\b", q, I):
        return "this year"
    if re.search(r"\blast year\b|\ba year ago\b", q, I):
        return "last year"
    if re.search(r"\b(recent(ly)?|lately|latest|newest|this (month|week)|(last|past) (few |couple( of)? )?(days|weeks?|months?))\b", q, I):
        return "recent"
    if re.search(r"\b(years ago|long ago|ages ago|back in the day|old (photos?|pictures?|pics?|videos?)|"
                 r"when (the )?(kids|someone|we|i|they) (were|was) (little|young|small|tiny|babies|a baby|kids))\b", q, I):
        return "long ago"
    return "any"


def no_people(q):
    return bool(re.search(r"\b(no|without|w/o|minus|free of|zero) (any )?(people|persons?|humans?|anyone|anybody|crowds?|faces?|one in (it|them))\b"
                          r"|\bnobody\b|\bno one\b|\bpeople-?free\b|\bempty\b|\bdeserted\b|\bjust (the )?(scenery|landscapes?|views?)\b", q, I))


def no_selfies(q):
    return bool(re.search(r"\b(no|without|not|skip|exclude|excluding|minus|except|but no|leave out|other than) "
                          r"(the |any |my )?(selfies?|self[- ]portraits?)\b", q, I))


def answer(q):
    return dict(kind=kind(q), season=season(q), when=when(q), no_people=no_people(q), no_selfies=no_selfies(q))
