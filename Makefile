PY ?= python

.PHONY: data index test eval-retrieval eval-answers app

data:            ## download the corpus and build chunks
	$(PY) -m ingest.download
	$(PY) -m ingest.chunk

index: data      ## embed chunks into DuckDB
	$(PY) -m index.store

test:
	$(PY) -m pytest -q

eval-retrieval:  ## retrieval ablation, no LLM
	HF_HUB_OFFLINE=1 $(PY) -m eval.run_eval retrieval

eval-answers:    ## end-to-end answers on the Claude plan (resumable)
	HF_HUB_OFFLINE=1 $(PY) -m eval.run_eval answers

app:
	HF_HUB_OFFLINE=1 streamlit run app/streamlit_app.py
