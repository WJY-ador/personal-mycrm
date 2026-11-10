'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {makeReleasePlan} = require('../scripts/codex-compat-release-plan.cjs');
const main = 'a'.repeat(40), old = 'b'.repeat(40), unrelated = 'c'.repeat(40);
test('includes current and supported immutable ancestor exactly once', () => {
  assert.deepEqual(makeReleasePlan(main, {supported_commits:[old,main,old]}, x => x === old || x === main), [main,old]);
});
test('rejects malformed and non-ancestor source commits', () => {
  for (const value of [{supported_commits:['main']},{supported_commits:[unrelated]}, {supported_commits:'bad'}, {other:[]}]) {
    assert.throws(() => makeReleasePlan(main, value, x => x === main || x === old));
  }
});

test('only published supported stable releases on main are selected', () => {
 const {selectReleased} = require('../scripts/codex-compat-release-plan.cjs');
 const releases=[{tagName:'v0.1.2'}, {tagName:'v0.2.0'}, {tagName:'v0.3.0-rc1'}];
 const lookup = tag => tag==='v0.1.2' ? {sha:old,version:'0.1.2',supports:false} : {sha:unrelated,version:'0.2.0',supports:true};
 assert.deepEqual(selectReleased(releases, lookup, sha => sha===unrelated || sha===old), [unrelated]);
 assert.throws(()=>selectReleased([{tagName:'v0.2.0'}],lookup,()=>false));
 assert.throws(()=>selectReleased([{tagName:'v0.2.0'}],()=>({sha:old,version:'0.2.1',supports:true}),()=>true));
});
