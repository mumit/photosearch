"""The launch video: photosearch in presenter mode, about 55 seconds. Captions say what the tool does, never more."""

pill = "[...document.querySelectorAll('#wregions .pill')].find(b => b.textContent.includes({!r}))"

# opened once before recording: the map's tiles and Galaxy's layout are loaded before they're shown
WARM = ["#world", "#galaxy"]

BEATS = [
    # 1. Home, then the hook: search by what's in the photo
    ("home", "__demo.caption('Search your photos by what’s <i>in</i> them', 'on your Mac · nothing leaves it')", 2.0),
    ("type", "await __demo.type('#q', 'a waterfall in the mist')", 0.4),
    ("search", "await __demo.click('#gobtn'); __demo.caption(null)", 2.6),

    # 2. Wander: every photo leads to its look-alikes
    ("open", "await __demo.click('#grid .tile:nth-child(2)'); __demo.caption('Every photo leads to its look-alikes')", 1.8),
    ("wander1", "await __demo.click('#lbsims img:nth-child(3)')", 1.5),
    ("wander2", "await __demo.click('#lbsims img:nth-child(2)')", 1.6),
    ("close", "await __demo.click('#lbclose'); __demo.caption(null)", 0.6),

    # 3. Galaxy: the whole library as a map of look-alikes, growing year by year, then lit up by a search
    ("galaxy", "await __demo.click('nav#tabs a[href=\"#galaxy\"]'); __demo.caption('Your whole library, as a map of look-alikes')", 2.4),
    ("grow", "await __demo.click('#gplay')", 6.6),
    ("light", "stopGrow(); setUpto(null); await __demo.type('#q', 'the ocean'); await __demo.click('#gobtn')", 2.8),

    # 4. Photo math
    ("math", "__demo.caption(null); location.hash = 'math'; __demo.caption('Photos you can do math on', 'a city skyline + night')", 1.0),
    ("math-base", "await __demo.type('#mtext', 'a city skyline')", 0.2),
    ("math-plus", "await __demo.type('#mplus', 'night')", 0.2),
    ("math-go", "await __demo.click('#mf button')", 2.8),

    # 5. The map, by the place names Photos knows
    ("map", "__demo.caption(null); await __demo.click('nav#tabs a[href=\"#world\"]'); __demo.caption('Everywhere you’ve been')", 2.6),
    ("region", f"await __demo.click({pill.format('Ottawa')})", 3.0),

    # 6. Out
    ("end", "__demo.caption('photosearch', 'open source · runs on your Mac'); __demo.hide()", 2.5),
]
