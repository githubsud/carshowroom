"""Write the API's OpenAPI schema for the Angular type generator (BACKLOG 1.10).

Usage: python scripts/export_openapi.py ../web/src/app/core/api/openapi.json
No database or network access is needed: the app is built but never started.
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql://unused@localhost/unused")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app

schema = create_app().openapi()
target = Path(sys.argv[1])
target.write_text(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {target} ({len(schema['paths'])} paths)")
