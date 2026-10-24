// Only user-authorized transport callback sites and declarations may change.
import { readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
const root = path.dirname(fileURLToPath(import.meta.url));
const packageRoot = path.join(root, 'node_modules/@earendil-works/pi-coding-agent');
const lock = JSON.parse(readFileSync(path.join(root, 'pi-patch.lock.json'), 'utf8'));
const pkg = JSON.parse(readFileSync(path.join(packageRoot, 'package.json'), 'utf8'));
if (pkg.version !== lock.pi_version || pkg.version !== '0.84.1') throw Error('Unapproved Pi version');
const hash = (s) => createHash('sha256').update(s).digest('hex');
for (const item of lock.files) {
  const filename = path.join(packageRoot, item.path);
  let text = readFileSync(filename, 'utf8');
  if (hash(text) === item.patched_sha256) continue;
  if (hash(text) !== item.original_sha256) throw Error(`Unrecognized original SDK file: ${item.path}`);
  for (const replacement of item.replacements) {
    if (text.split(replacement.before).length !== 2) throw Error('Patch context not unique');
    text = text.replace(replacement.before, replacement.after);
  }
  if (hash(text) !== item.patched_sha256) throw Error('Patched SDK hash differs from lock');
  writeFileSync(filename, text);
}
process.stderr.write('Verified Pi 0.84.1 locked remote-IO callback patches\n');
