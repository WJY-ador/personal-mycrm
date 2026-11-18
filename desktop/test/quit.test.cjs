'use strict';
// How the app ends (spec 2026-11-18 §1.1). The pure parts run here with a fake dialog; main.cjs wiring is checked in
// its source, as the other main.cjs tests do (Electron does not run under node --test).
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {TRAY_QUIT_LABEL,HIDE_LABEL,QUIT_DIALOG,hideAccelerator,createQuitConfirm}=require('../src/quit.cjs');

const main=fs.readFileSync(path.join(__dirname,'..','src','main.cjs'),'utf8');
function fakeDialog(response){
  const shown=[];let release;
  return {shown,
    showMessageBox:(...args)=>{shown.push(args);if(response==='hold')return new Promise(r=>{release=()=>r({response:1});});
      if(response instanceof Error)return Promise.reject(response);return Promise.resolve({response});},
    release:()=>release()};
}

test('the confirmation: fixed text, quit button first, cancel is the default and the Esc answer, no punctuation marks',()=>{
  assert.equal(TRAY_QUIT_LABEL,'완전히 종료');
  assert.equal(QUIT_DIALOG.message,'끄면 웹 AI 대화와 자동 수집이 멈춰요. PC 앱을 다시 열 때까지 대화할 수 없어요.');
  assert.deepEqual([...QUIT_DIALOG.buttons],['완전히 종료','취소']);
  assert.equal(QUIT_DIALOG.defaultId,1);assert.equal(QUIT_DIALOG.cancelId,1);
  for(const text of [QUIT_DIALOG.message,...QUIT_DIALOG.buttons,TRAY_QUIT_LABEL,HIDE_LABEL])assert.doesNotMatch(text,/[「」·]/);
});

test('tray quit: confirming quits once, without a parent window',async()=>{
  const d=fakeDialog(0);let quits=0,focused=0;
  const confirm=createQuitConfirm({dialog:d,quit:()=>quits++,blocked:()=>false,focus:()=>{focused++;assert.equal(d.shown.length,0);}});
  assert.equal(await confirm(),true);
  assert.equal(focused,1,'the app comes to the front before the dialog');
  assert.equal(quits,1);
  assert.equal(d.shown.length,1);assert.equal(d.shown[0].length,1,'options only: a sheet on a hidden window is never seen');
  assert.equal(d.shown[0][0].defaultId,1);
});

test('tray quit: cancel (button, Esc) or a failed dialog keeps the app running',async()=>{
  for(const answer of [1,new Error('dialog')]){
    let quits=0;
    const confirm=createQuitConfirm({dialog:fakeDialog(answer),quit:()=>quits++,blocked:()=>false});
    assert.equal(await confirm(),false);assert.equal(quits,0);
  }
});

test('tray quit: one dialog at a time, none while quitting or installing an update',async()=>{
  const d=fakeDialog('hold');let quits=0;
  const confirm=createQuitConfirm({dialog:d,quit:()=>quits++,blocked:()=>false});
  const first=confirm();
  assert.equal(await confirm(),false,'a second click while the dialog is open');
  d.release();assert.equal(await first,false);
  assert.equal(d.shown.length,1);
  let blocked=true;const busy=fakeDialog(0);
  const held=createQuitConfirm({dialog:busy,quit:()=>quits++,blocked:()=>blocked});
  assert.equal(await held(),false);assert.equal(busy.shown.length,0);
  // The update install starts while the dialog is open: the late confirm does not quit a second time.
  blocked=false;const late={showMessageBox:async()=>{blocked=true;return {response:0};}};
  assert.equal(await createQuitConfirm({dialog:late,quit:()=>quits++,blocked:()=>blocked})(),false);
  assert.equal(quits,0);
});

test('Command+Q and Alt+F4 hide the window',()=>{
  assert.equal(hideAccelerator('darwin'),'Command+Q');
  assert.equal(hideAccelerator('win32'),'Alt+F4');
  assert.match(main,/\{label:HIDE_LABEL,accelerator:hideAccelerator\(process\.platform\),click:hideDashboard\}/);
  assert.match(main,/function hideDashboard\(\)\{if\(dash&&!dash\.isDestroyed\(\)\)dash\.hide\(\);\}/);
});

test('main: the tray item is the only menu item that ends the app, and it asks first',()=>{
  assert.match(main,/\{label:TRAY_QUIT_LABEL,click:\(\)=>\{confirmQuit\(\)\.catch\(\(\)=>\{\}\);\}\}/);
  assert.match(main,/const confirmQuit=createQuitConfirm\(\{dialog,quit:\(\)=>app\.quit\(\),blocked:\(\)=>quitting\|\|installing,focus:\(\)=>app\.focus\(\{steal:true\}\)\}\);/);
  // app.quit() is called by: the second instance, the confirmed tray quit, and before-quit's own cleanup. No menu click.
  assert.equal((main.match(/app\.quit\(\)/g)||[]).length,3);
  assert.doesNotMatch(main,/click:\(\)=>app\.quit\(\)/);
  assert.doesNotMatch(main,/label:'종료'/);
});

test('main: an update install and an OS logout or shutdown are not held',()=>{
  // The window closes for the update (installing) and for a Windows session end (sessionEnding).
  assert.match(main,/dash\.on\('close',event=>\{if\(!quitting&&!installing&&!sessionEnding\)\{event\.preventDefault\(\);dash\.hide\(\);\}\}\);/);
  assert.match(main,/dash\.on\('session-end',\(\)=>\{sessionEnding=true;\}\);/);
  assert.match(main,/nativeUpdater\.on\('before-quit-for-update',\(\)=>\{installing=true;\}\)/);
  // before-quit (macOS Dock quit, logout, shutdown, the update's quit) only runs the cleanup and quits again; nothing
  // here decides to stay open.
  const beforeQuit=/app\.on\('before-quit',event=> \{[\s\S]*?\n  \}\);/.exec(main)?.[0]||'';
  assert.ok(beforeQuit,'before-quit handler exists');
  assert.match(beforeQuit,/if\(quitting\)return;event\.preventDefault\(\);quitting=true;/);
  assert.match(beforeQuit,/\.finally\(\(\)=>\{tray\?\.destroy\(\);app\.quit\(\);\}\);/);
  assert.doesNotMatch(beforeQuit,/hide\(|confirmQuit|showMessageBox/);
  assert.doesNotMatch(main,/app\.on\('(will-quit|window-all-closed)'/);
});
