# ZSH configuration

# History
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
setopt SHARE_HISTORY
setopt HIST_IGNORE_DUPS

# Completion
autoload -Uz compinit
compinit

# Plugins
[[ -f /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh ]] && \
    source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh

[[ -f /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]] && \
    source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# Starship prompt
eval "$(starship init zsh)"
export PATH="$HOME/.local/bin:$PATH"
export KUBECONFIG=~/.kube/config
export PATH="$(npm config get prefix)/bin:$PATH"

# jump into a persistent tmux session running claude, mainly for phone/mosh
# use over an unstable connection - survives disconnects, screen lock, etc.
claude-mobile() {
    tmux attach -t claude 2>/dev/null || tmux new -s claude "claude -r"
}

if [[ -n "$SSH_CONNECTION" && -z "$TMUX" ]]; then
    echo "tip: run 'claude-mobile' for a persistent claude session that survives dropped connections"
fi
