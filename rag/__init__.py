import os

# The Xet transfer backend can stall on slow links; plain HTTPS downloads are reliable.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
