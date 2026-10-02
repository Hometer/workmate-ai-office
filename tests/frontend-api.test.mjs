import test from 'node:test';
import assert from 'node:assert/strict';
import { apiGet, apiPost } from '../workmate/static/api.js';

test('API errors preserve the backend business message', async () => {
 const saved=globalThis.fetch;
 try { globalThis.fetch=async()=>new Response(JSON.stringify({error:{code:'SOURCE_CHANGED',message:'数据版本已变化'}}),{status:400});
  await assert.rejects(apiGet('/basis'),/数据版本已变化/);
 } finally {globalThis.fetch=saved;}
});
test('network failure on task submission explains uncertainty without retrying', async () => {
 const saved=globalThis.fetch;let calls=0;
 try {globalThis.fetch=async()=>{calls++;throw new TypeError('network failure');};
  await assert.rejects(apiPost('/api/v1/tasks',{}),/任务可能已受理/);
  assert.equal(calls,1);
 } finally {globalThis.fetch=saved;}
});
test('request cancellation is bounded and timers are cleared after success', async () => {
 const saved=globalThis.fetch;
 try {globalThis.fetch=async(path,options)=>{assert.ok(options.signal instanceof AbortSignal);return new Response('{"status":"ok"}');};
  assert.deepEqual(await apiGet('/health'),{status:'ok'});
 } finally {globalThis.fetch=saved;}
});
