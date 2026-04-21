# fish completion for soctriage
# Generated from soctriage.cli.build_parser
# Regenerate: python -m shtab --shell=fish soctriage.cli.build_parser

complete -c soctriage -s h -l help       -d 'Show help and exit'
complete -c soctriage      -l version    -d 'Show version and exit'
complete -c soctriage      -l verbose    -d 'Enable debug output'
complete -c soctriage      -l input      -r -F -d 'Input log file path or - for stdin'
complete -c soctriage      -l output     -r -F -d 'Output report base path'
complete -c soctriage      -l format     -r    -d 'Output format' -a 'json markdown html'
complete -c soctriage      -l include-raw       -d 'Include raw event text in JSON output'
complete -c soctriage      -l no-llm            -d 'Skip LLM agent'
complete -c soctriage      -l llm-backend -r    -d 'LLM backend' -a 'anthropic ollama'
complete -c soctriage      -l llm-model   -r    -d 'LLM model name'
complete -c soctriage      -l ollama-host -r    -d 'Ollama API host URL'
complete -c soctriage      -l timeout     -r    -d 'LLM call timeout in seconds'
complete -c soctriage      -l asic-gen    -r    -d 'Override ASIC generation'
complete -c soctriage      -l soc-provider -r   -d 'Force SoC provider' -a 'intel qualcomm amd nvidia generic'
complete -c soctriage      -l list-providers    -d 'List registered providers and exit'
complete -c soctriage      -l token-rule  -r    -d 'Inject inline token rule (TYPE:PATTERN)'
complete -c soctriage      -l plugin      -r -F -d 'Load Python plugin file'
