# The Claude half of the launch video, recorded by VHS. claude_take.py fills in {out}, {work} and {prompt}; run that
# rather than this file. Claude runs with its own config folder (~/.claude-demo), only the demo's MCP server, and only
# its tools allowed, and the shell is started clean (env -i) so nothing from this session leaks into the banner.
Output "{out}"
Set Shell "zsh"
Set FontSize 17
Set Width 1000
Set Height 1080
Set Padding 28
Set TypingSpeed 55ms
Set Theme "Catppuccin Mocha"
Hide
Type "PS1='~/demo $ ' && cd {work} && clear" Enter
Sleep 500ms
Type "env -i HOME=$HOME PATH=$PATH USER=$USER LOGNAME=$LOGNAME SHELL=/bin/zsh TMPDIR=$TMPDIR TERM=xterm-256color LANG=en_US.UTF-8 CLAUDE_CONFIG_DIR=$HOME/.claude-demo claude --mcp-config .mcp-demo.json --strict-mcp-config --allowedTools mcp__photosearch-demo" Enter
Sleep 8s
Show
Sleep 1.5s
Type `{prompt}`
Sleep 800ms
Enter
# A fixed wait, never a Wait for text: when a Wait times out, VHS throws the whole recording away. edit.py finds
# where Claude finished and trims the rest.
Sleep {wait}s
