.PHONY: completions install-completions man test bench clean

completions:
	mkdir -p completions
	python -m shtab --shell=bash soctriage.cli.build_parser > completions/soctriage.bash
	python -m shtab --shell=zsh  soctriage.cli.build_parser > completions/soctriage.zsh
	python -m shtab --shell=fish soctriage.cli.build_parser > completions/soctriage.fish

install-completions: completions
	install -Dm644 completions/soctriage.bash /etc/bash_completion.d/soctriage
	install -Dm644 completions/soctriage.zsh  /usr/share/zsh/site-functions/_soctriage
	install -Dm644 completions/soctriage.fish /usr/share/fish/completions/soctriage.fish

man:
	mkdir -p man
	argparse-manpage \
		--pyfile soctriage/cli.py \
		--function build_parser \
		--author "SD Move" \
		--project-name soctriage \
		--url "https://github.com/sdmove/soctriage" \
		> man/soctriage.1

test:
	pytest --tb=short -q

bench:
	pytest benchmarks/ --benchmark-only -q

clean:
	rm -rf dist/ build/ *.egg-info .pytest_cache __pycache__
