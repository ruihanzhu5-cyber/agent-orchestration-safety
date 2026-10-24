// A negative SDK compatibility probe, not a substituted search tool.
import fs from 'node:fs';
import path from 'node:path';
import cp from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {pathToFileURL} from 'node:url';

const [sdkRoot, evidenceDir] = process.argv.slice(2);
if (!sdkRoot || !evidenceDir) throw new Error('SDK root and isolated evidence directory required');
process.env.PI_CODING_AGENT_DIR = path.join(evidenceDir, 'isolated-agent');
process.env.PI_OFFLINE = '1';
const evidence = {synthetic: true, real_model_requests: 0, real_judge_requests: 0,
  network_attempts: 0, local_exec_attempts: [], custom_operations: []};
globalThis.fetch = async () => { evidence.network_attempts++; throw new Error('NETWORK_GUARD'); };
const config = await import(pathToFileURL(path.join(sdkRoot, 'dist/config.js')).href);
const bin = config.getBinDir();
if (!path.resolve(bin).startsWith(path.resolve(evidenceDir) + path.sep)) throw new Error('Unexpected tool cache path');
fs.mkdirSync(bin, {recursive:true});
fs.writeFileSync(path.join(bin,'rg'), 'never execute this sentinel\n');
const sdk = await import(pathToFileURL(path.join(sdkRoot,'dist/index.js')).href);
const original = {spawn:cp.spawn, spawnSync:cp.spawnSync};
function trap(program) {
  evidence.local_exec_attempts.push({program:path.basename(String(program))});
  throw new Error('HOST_EXEC_TRAP: local process execution despite remote Operations');
}
cp.spawn = trap;
cp.spawnSync = trap;
syncBuiltinESMExports();
const tool = sdk.createGrepToolDefinition('/workspace', {operations:{
  isDirectory: async p => { evidence.custom_operations.push({operation:'isDirectory',path:p}); return true; },
  readFile: async p => { evidence.custom_operations.push({operation:'readFile',path:p}); return 'remote-only marker\n'; }
}});
try {
  await tool.execute('compatibility-probe', {pattern:'marker',path:'/workspace'}, new AbortController().signal, undefined, {});
  evidence.status = 'unexpected_no_failure';
} catch (error) {
  evidence.status = evidence.local_exec_attempts.length ? 'BLOCKED_HOST_EXEC_WITH_CUSTOM_OPERATIONS' : 'BLOCKED_OTHER';
  evidence.error = String(error.message);
} finally {
  cp.spawn = original.spawn;
  cp.spawnSync = original.spawnSync;
  syncBuiltinESMExports();
  fs.mkdirSync(evidenceDir,{recursive:true});
  fs.writeFileSync(path.join(evidenceDir,'sdk-grep-probe.json'), JSON.stringify(evidence,null,2)+'\n');
}
console.log(JSON.stringify(evidence));
process.exitCode = evidence.local_exec_attempts.length ? 1 : 2;
