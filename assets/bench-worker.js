/* Runs in the visitor's browser, never on ProofCheck's hosting server. */
'use strict';
self.onmessage = function(event) {
  const kind = event.data?.kind;
  try {
    const t0 = performance.now();
    if (kind === 'cpu') {
      // Fixed-size mixed integer workload; elapsed time depends heavily on browser.
      let value = 2166136261 >>> 0;
      const iterations = 2_000_000;
      for (let i = 0; i < iterations; i++) {
        value = Math.imul(value ^ (i & 255), 16777619) >>> 0;
      }
      const elapsed = Math.max(performance.now() - t0, .01);
      self.postMessage({ok:true, kind, iterations, checksum:value, ms:+elapsed.toFixed(2)});
    } else if (kind === 'memory') {
      // Touch 8 MiB in browser memory. This is NOT a physical RAM error test.
      const arr = new Uint32Array(2 * 1024 * 1024);
      let check = 0;
      for (let i = 0; i < arr.length; i += 16) arr[i] = (i ^ 0x5a5a5a5a) >>> 0;
      for (let i = 0; i < arr.length; i += 16) check = (check ^ arr[i]) >>> 0;
      const elapsed = Math.max(performance.now() - t0, .01);
      self.postMessage({ok:true,kind,bytes:arr.byteLength, checksum:check, ms:+elapsed.toFixed(2)});
    } else { self.postMessage({ok:false,error:'Unknown browser test'}); }
  } catch (err) { self.postMessage({ok:false,error:String(err.message||err)}); }
};
