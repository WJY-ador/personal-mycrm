'use strict';
// How the app ends (spec 2026-11-18 §1.1): the app ends only when the person chooses it. Command+Q and the app menu
// item (Alt+F4 on Windows) hide the window like its close button. The one way to end it is the tray's "완전히 종료",
// after one confirmation whose default button is cancel. An in-app update install and an OS logout or shutdown are not
// held: main.cjs adds no preventDefault of its own to before-quit, and the window closes for them (installing,
// sessionEnding).
const TRAY_QUIT_LABEL='완전히 종료';
const HIDE_LABEL='창 닫기';
const QUIT_DIALOG=Object.freeze({
  type:'warning',title:'MyCRM',
  message:'끄면 웹 AI 대화와 자동 수집이 멈춰요. PC 앱을 다시 열 때까지 대화할 수 없어요.',
  buttons:Object.freeze([TRAY_QUIT_LABEL,'취소']),defaultId:1,cancelId:1,noLink:true,
});
// The shortcut that used to quit now hides the window: Command+Q on macOS, Alt+F4 on Windows.
function hideAccelerator(platform){return platform==='darwin'?'Command+Q':'Alt+F4';}
// The tray's quit. No parent window: the window may be hidden, and a sheet on a hidden window is never seen.
// focus brings the app to the front first (the tray click leaves another app in front on macOS). One dialog at a time;
// none while the app is already quitting or installing an update. Resolves true when it quit.
function createQuitConfirm({dialog,quit,blocked,focus=()=>{}}){
  let open=false;
  return async function confirmQuit(){
    if(open||blocked())return false;
    open=true;
    try{
      try{focus();}catch{}
      const {response}=await dialog.showMessageBox({...QUIT_DIALOG,buttons:[...QUIT_DIALOG.buttons]});
      if(response!==0||blocked())return false;
      quit();return true;
    }catch{return false;}
    finally{open=false;}
  };
}
module.exports={TRAY_QUIT_LABEL,HIDE_LABEL,QUIT_DIALOG,hideAccelerator,createQuitConfirm};
