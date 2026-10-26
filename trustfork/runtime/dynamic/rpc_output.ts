/** Durable disk FIFO with one bounded stdout buffer; no unbounded Promise/frame queue. */
import {openSync,writeSync,readSync,fsyncSync,ftruncateSync,closeSync} from 'node:fs';
import type {Writable} from 'node:stream';
export class RpcOutput {
 private fd:number;private written=0;private read=0;private pumping:Promise<void>|null=null;private failure:Error|null=null;private closed=false;
 private accepted=0;private persisted=0;private processed=0;private highWater=0;private peakRss=0;private frames=0;
 private output:Writable;private chunkBytes:number;
 constructor(filename:string,output:Writable,chunkBytes=64*1024){this.output=output;this.chunkBytes=chunkBytes;this.fd=openSync(filename,'w+',0o600);}
 enqueue(row:unknown):void {
  if(this.failure)throw this.failure;if(this.closed)throw Error('RPC output closed');
  const raw=Buffer.from(JSON.stringify(row)+'\n');this.accepted+=raw.length;
  let position=0;while(position<raw.length)position+=writeSync(this.fd,raw,position,raw.length-position,this.written+position);
  fsyncSync(this.fd);this.written+=raw.length;this.persisted+=raw.length;this.frames++;
  this.highWater=Math.max(this.highWater,this.written-this.read);this.peakRss=Math.max(this.peakRss,process.memoryUsage().rss);
  if(!this.pumping)this.pumping=this.pump();
 }
 private async pump():Promise<void>{
  // Yield so enqueue never races assignment of the single pump promise.
  await new Promise<void>(r=>setImmediate(r));
  try{
   while(this.read<this.written){
    const buffer=Buffer.allocUnsafe(Math.min(this.chunkBytes,this.written-this.read));
    const n=readSync(this.fd,buffer,0,buffer.length,this.read);if(!n)throw Error('RPC spool truncated');
    await new Promise<void>((resolve,reject)=>{this.output.write(buffer.subarray(0,n),error=>error?reject(error):resolve());});
    this.read+=n;this.processed+=n;
   }
   ftruncateSync(this.fd,0);this.read=0;this.written=0;
  }catch(error){this.failure=error as Error;throw error;}
  finally{this.pumping=null;}
 }
 stats(){return {accepted_bytes:this.accepted,persisted_bytes:this.persisted,processed_bytes:this.processed,pending_disk_bytes:this.written-this.read,queue_high_water_bytes:this.highWater,max_output_buffer_bytes:this.chunkBytes,peak_rss_bytes:this.peakRss,frames:this.frames};}
 async flush(){while(this.pumping)await this.pumping;if(this.failure)throw this.failure;}
 async close(){await this.flush();if(!this.closed){fsyncSync(this.fd);closeSync(this.fd);this.closed=true;}}
}
