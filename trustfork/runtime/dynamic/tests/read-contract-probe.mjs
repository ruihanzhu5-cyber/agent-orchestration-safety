// Negative compatibility probe: task paths must never touch the host filesystem.
import fsPromises from 'node:fs/promises';
import { syncBuiltinESMExports } from 'node:module';
import { createReadToolDefinition } from '@earendil-works/pi-coding-agent';
const access = fsPromises.access;
const attempts = [];
fsPromises.access = async (file, ...args) => {
  if (String(file).startsWith('/workspace')) {
    attempts.push(String(file));
    throw new Error('HOST_FS_TRAP');
  }
  return access(file, ...args);
};
syncBuiltinESMExports();
const operations = [];
const tool = createReadToolDefinition('/workspace', {operations: {
  access: async (p) => {operations.push(['access', p]);},
  readFile: async (p) => {operations.push(['readFile', p]); return Buffer.from('remote fixture');},
  detectImageMimeType: async () => undefined,
}});
await tool.execute('negative-read', {path: '/workspace/file.txt'}, undefined, undefined, {});
fsPromises.access = access;
syncBuiltinESMExports();
console.log(JSON.stringify({synthetic:true, pi_version:'0.84.1', local_fs_attempts:attempts,
  custom_operations:operations, real_model_requests:0, real_judge_requests:0,
  status: attempts.length ? 'BLOCKED_HOST_PATH_PROBE_WITH_CUSTOM_OPERATIONS' : 'pass'}));
if (attempts.length) process.exitCode = 1;
