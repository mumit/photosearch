# The Claude half of the launch video: Claude Code making "Best hikes" from the demo library through photosearch's
# MCP server, as in the first launch video. reset.py writes the MCP config into the work
# folder and removes the last take's album. Claude runs with its own config folder (~/.claude-demo), only the demo's
# MCP server and only its tools allowed, and the shell is started clean (env -i) so nothing from this Mac shows.
# DISABLE_AUTOUPDATER keeps "Update installed · Restart to apply" out of the take.
Output "takes/claude.mp4"
Set Shell "zsh"
Set FontSize 17
Set Width 1000
Set Height 1080
Set Padding 28
Set TypingSpeed 55ms
Set Theme "Catppuccin Mocha"
Hide
Type "PS1='~/demo $ ' && cd /tmp/photosearch-demo && clear" Enter
Sleep 500ms
Type "env -i HOME=$HOME PATH=$PATH USER=$USER LOGNAME=$LOGNAME SHELL=/bin/zsh TMPDIR=$TMPDIR TERM=xterm-256color LANG=en_US.UTF-8 DISABLE_AUTOUPDATER=1 CLAUDE_CONFIG_DIR=$HOME/.claude-demo claude --mcp-config .mcp-demo.json --strict-mcp-config --allowedTools mcp__photosearch-demo" Enter
Sleep 8s
Show
Sleep 1.5s
Type `Make an album called "Best hikes" from my photos: trails, forests and views from the top. No people, nothing blurry, so look at them before you add any.`
Sleep 800ms
Enter
# A fixed wait, never a Wait for text: when a Wait times out, VHS throws the whole recording away. edit.py finds
# where Claude finished and trims the rest.
Sleep 285s
