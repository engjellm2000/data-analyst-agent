.PHONY: data eval demo test

data:
	python -m app.seed

eval:
	python -m evals.run_evals

demo: data eval
	python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log

test:
	python -m pytest -q
