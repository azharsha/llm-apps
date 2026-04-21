# bash completion for soctriage
# Generated from soctriage.cli.build_parser
# Regenerate: python -m shtab --shell=bash soctriage.cli.build_parser

_soctriage() {
    local cur prev words cword
    _init_completion || return

    local opts="--input --output --format --verbose --llm --model --ip-detail
                --asic-gen --soc-provider --list-providers --token-rule --plugin
                --no-llm --llm-backend --llm-model --ollama-host --timeout
                --include-raw --version --help"

    case "${prev}" in
        --format)
            COMPREPLY=($(compgen -W "json markdown html" -- "${cur}"))
            return ;;
        --llm-backend)
            COMPREPLY=($(compgen -W "anthropic ollama" -- "${cur}"))
            return ;;
        --input|--output|--plugin)
            COMPREPLY=($(compgen -f -- "${cur}"))
            return ;;
        --soc-provider)
            COMPREPLY=($(compgen -W "intel qualcomm amd nvidia generic" -- "${cur}"))
            return ;;
    esac

    if [[ "${cur}" == -* ]]; then
        COMPREPLY=($(compgen -W "${opts}" -- "${cur}"))
    else
        COMPREPLY=($(compgen -f -- "${cur}"))
    fi
}

complete -F _soctriage soctriage
