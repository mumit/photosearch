# photosearch launch video, recorded again

- Audience: Mac users with a large Apple Photos library, and people who use Claude Code.
- Problem they recognize: finding a photo by what's in it, not by date or album.
- What it shows: the original launch script on today's photosearch, plus two things it does since. Search by
  description, ? Why a photo matched, wander through look-alikes, Galaxy growing year by year and lit up by a
  search, Photo Math, the map, Then and Now (the same spot years apart), then Claude Code making a "Best hikes"
  album through photosearch's MCP server, and that album in Photos.
- Visible result that proves it worked: the matching photos, and the album Claude made shown in Photos.
- Destination and length: a landscape MP4 of about 100 s (web, then Claude at a labelled 8x, then an end card),
  a README GIF with a moment from each feature, a GIF per section for posts, and a short cut of the two new beats.
- Next action: github.com/mumit/photosearch.
- Script source: the first launch video's own tools (a storyboard, a VHS tape and a cut script, since retired).
  Same beats, captions, prompt, album and end card, with the two new beats. Selectors checked against today's UI.
- Data: the separate "Photosearch Demo" Photos library (~/Pictures) and its index in photosearch's
  data-demo/, whose photos the owner checked by eye for the first launch video. Never the owner's own library.
  The server runs in presenter mode (`--demo`). Claude runs from its own config folder (~/.claude-demo) with only
  the demo's MCP server allowed.
- Reset: reset.py refuses unless Photos has the demo library open, deletes the last take's "Best hikes" album
  (the album only) and writes the MCP config to /tmp/photosearch-demo.
- Nothing mocked: real search, real Claude. Claude's working time is sped up 8x and labelled.
- The home page's archive banner and Rediscover shelf pick photos at random from the demo library, so each take
  shows different ones.

Inspect a preview before recording a fresh final. Recording acceptance and scan-sheet approval are the owner's.
