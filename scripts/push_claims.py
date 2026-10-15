"""Send mock MIS claims (configs/claims.yaml) to the server."""
import sys
from pathlib import Path

import httpx
import yaml

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
claims = yaml.safe_load((Path(__file__).resolve().parents[1] / "configs/claims.yaml").read_text())
for c in claims:
    c["start"], c["end"] = c["start"].isoformat(), c["end"].isoformat()
print(httpx.post(f"{url}/api/v1/claims", json=claims, timeout=30).json())
