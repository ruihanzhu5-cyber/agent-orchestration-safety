/** The RPC subset of the shared Draft 2020-12 contract, also checked in Python. */
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const contracts=JSON.parse(readFileSync(fileURLToPath(new URL('../../config/dynamic/contracts.schema.json',import.meta.url)),'utf8'));
export function assertBridgeEnvelope(value:any):void{
  const schema=contracts.$defs.BridgeEnvelope;
  if(value===null||typeof value!=='object'||Array.isArray(value))throw Error('RPC envelope must be an object');
  for(const key of schema.required)if(!(key in value))throw Error('Missing RPC field: '+key);
  for(const key of Object.keys(value)){
    const spec=schema.properties[key];
    if(!spec)throw Error('Unknown RPC field: '+key);
    const item=value[key];
    if(spec.enum&&!spec.enum.includes(item))throw Error('Invalid RPC enum: '+key);
    const types=Array.isArray(spec.type)?spec.type:[spec.type];
    if(spec.type&&!types.some((type:string)=>type==='null'?item===null:
      type==='integer'?Number.isInteger(item):type==='object'?(item!==null&&typeof item==='object'&&!Array.isArray(item)):
      typeof item===type))throw Error('Invalid RPC type: '+key);
    if(spec.minimum!==undefined&&item<spec.minimum)throw Error('Invalid RPC minimum: '+key);
  }
}
