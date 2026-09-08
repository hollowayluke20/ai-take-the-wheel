install:
    pip install -e ".[dev]"

test:
    pytest -q

lint:
    ruff check src tests scripts

validate:
    python scripts/validate_answers.py

check: lint test validate
    @echo OK
