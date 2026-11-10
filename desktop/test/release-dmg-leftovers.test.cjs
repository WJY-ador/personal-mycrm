'use strict';
// desktop/scripts/dmg-leftovers.cjs: which attached images the mac dist retry may detach.
const test = require('node:test');
const assert = require('node:assert/strict');
const { leftoverDevices } = require('../scripts/dmg-leftovers.cjs');

const OUT = '/Users/runner/work/personal-mycrm/personal-mycrm/release/desktop';

// Shape of `hdiutil info -plist` converted to JSON: one entry per attached image.
const INFO = {
  images: [
    { 'image-path': '/Users/runner/Downloads/Other-1.0.dmg',
      'system-entities': [{ 'dev-entry': '/dev/disk6' }, { 'dev-entry': '/dev/disk6s1', 'mount-point': '/Volumes/Other' }] },
    { 'image-path': `${OUT}/.temp8k2jx_MyCRM-0.2.0-mac-x64.dmg`,
      'system-entities': [{ 'dev-entry': '/dev/disk2' }, { 'dev-entry': '/dev/disk2s1', 'mount-point': '/Volumes/MyCRM 0.2.0' }] },
    { 'image-path': `${OUT}/MyCRM-0.2.0-mac-x64.dmg`,
      'system-entities': [{ 'dev-entry': '/dev/disk3' }] },
    { 'image-path': `${OUT}/sub/.tempabcMyCRM-0.2.0-mac-x64.dmg`,
      'system-entities': [{ 'dev-entry': '/dev/disk4' }] },
  ],
};

test('only the dmgbuild temp image in the output folder is detached, by its whole-disk device', () => {
  assert.deepEqual(leftoverDevices(INFO, OUT), ['/dev/disk2']);
});

test('nothing attached, or nothing of ours, detaches nothing', () => {
  assert.deepEqual(leftoverDevices({ images: [] }, OUT), []);
  assert.deepEqual(leftoverDevices({}, OUT), []);
  assert.deepEqual(leftoverDevices(INFO, '/elsewhere'), []);
});
