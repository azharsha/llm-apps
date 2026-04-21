#compdef soctriage
# zsh completion for soctriage
# Generated from soctriage.cli.build_parser
# Regenerate: python -m shtab --shell=zsh soctriage.cli.build_parser

_soctriage() {
    local -a args
    args=(
        '(-h --help)'{-h,--help}'[show help and exit]'
        '--version[show version and exit]'
        '--verbose[enable debug output]'
        '--input[input log file path]:file:_files'
        '--output[output report base path]:file:_files'
        '--format[output format]:format:(json markdown html)'
        '--include-raw[include raw event text in JSON output]'
        '--no-llm[skip LLM agent]'
        '--llm-backend[LLM backend]:backend:(anthropic ollama)'
        '--llm-model[LLM model name]:model:'
        '--ollama-host[Ollama API host]:url:'
        '--timeout[LLM call timeout in seconds]:seconds:'
        '--asic-gen[override ASIC generation]:gen:'
        '--soc-provider[force SoC provider]:provider:(intel qualcomm amd nvidia generic)'
        '--list-providers[list registered providers and exit]'
        '--token-rule[inject inline token rule]:rule:'
        '--plugin[load Python plugin file]:file:_files'
        ':log file:_files'
    )
    _arguments -s $args
}

_soctriage "$@"
