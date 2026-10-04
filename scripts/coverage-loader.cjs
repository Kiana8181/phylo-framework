// Test-only post-SWC instrumentation. Production builds never load this loader.
const {createInstrumenter} = require('istanbul-lib-instrument');
module.exports = function (source, inputMap) {
  const instrumenter = createInstrumenter({
    esModules: true,
    produceSourceMap: true,
    compact: false,
    coverageGlobalScope: 'globalThis',
    coverageGlobalScopeFunc: false,
  });
  const output = instrumenter.instrumentSync(source, this.resourcePath, inputMap);
  this.callback(null, output, instrumenter.lastSourceMap());
};
