// Regenerate the Angular API types from the FastAPI schema:
//   npm run api:types          (from apps/web)
// CI runs this and fails if the committed files differ (contract drift).
import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';

const python = process.platform === 'win32' ? '../api/.venv/Scripts/python.exe' : '../api/.venv/bin/python';
const interpreter = existsSync(python) ? python : 'python';
execFileSync(interpreter, ['../api/scripts/export_openapi.py', 'src/app/core/api/openapi.json'], { stdio: 'inherit' });
// openapi-typescript needs TypeScript 5 internally while Angular 22 uses 6, so it runs in its own
// npx environment; the generated .d.ts is plain TypeScript that works with either.
execFileSync(
  'npx',
  ['--yes', '-p', 'openapi-typescript@7', '-p', 'typescript@5', 'openapi-typescript',
   'src/app/core/api/openapi.json', '-o', 'src/app/core/api/schema.d.ts'],
  { stdio: 'inherit', shell: true },
);
