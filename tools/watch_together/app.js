const $=id=>document.getElementById(id);
const {PlaybackClock,parsePosition,formatPosition,windowCues}=WatchTimeline;
const clock=new PlaybackClock();
let session=null,stream=null,paused=false,timer=null,heartbeat=null,sequence=0,inFlight=false,epoch=0;
let cues=[],lastPosition=null,loading=false,revision=0;
async function api(path,data={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const result=await r.json();if(!r.ok)throw Error(result.error||'操作失败');return result;}
function status(s){$('status').textContent=s;}
function resetReadout(){ $('ocrStatus').textContent='等待新的画面分析'; $('ocrText').textContent=''; }
function showReadout(result){
const lines=result.screenshot_subtitles;
const at=Number.isFinite(result.analysis_position)?formatPosition(result.analysis_position):'播放时间未知';
$('ocrStatus').textContent=`最近分析 · ${at} · ${Array.isArray(lines)?(lines.length?'已识别字幕':'未读到清晰字幕'):'本轮未返回识别结果'}`;
$('ocrText').textContent=Array.isArray(lines)?lines.join('\n'):'';
}

async function connect(){return api('/connect',{backend:$('backend').value.trim(),token:$('token').value.trim()});}
$('connect').onclick=async()=>{try{await connect();status('已连接左然');}catch(e){status(e.message);}};
$('subtitle').onchange=async()=>{if(session)return;const file=$('subtitle').files[0];cues=[];lastPosition=null;if(!file){$('subtitleStatus').textContent='会尝试阅读画面中的字幕，请打开播放器字幕';return;}
loading=true;$('start').disabled=true;try{if(file.size>500000)throw Error('字幕文件请小于500KB');const bytes=await file.arrayBuffer();let content;try{content=new TextDecoder('utf-8',{fatal:true}).decode(bytes);}catch{content=new TextDecoder('gb18030',{fatal:true}).decode(bytes);}
cues=(await api('/subtitles',{content})).cues;$('subtitleStatus').textContent=`已在本机载入 ${cues.length} 条字幕。请校准播放器时间。`;
}catch(e){$('subtitleStatus').textContent='字幕载入失败：'+e.message;$('subtitle').value='';}finally{loading=false;$('start').disabled=false;}};
function refreshTimeline(){const position=clock.position();$('playhead').textContent=formatPosition(position);const played=cues.filter(c=>c.end<=position).slice(-2);$('subtitlePreview').textContent=played.map(c=>c.text).join('\n')||'此进度还没有已播放完的字幕';}
setInterval(refreshTimeline,1000);
$('sync').onclick=async()=>{const before=paused;try{const position=parsePosition($('position').value),rate=Number($('speed').value);if(!Number.isFinite(rate)||rate<.25||rate>3)throw Error('倍速应在0.25到3之间');
if(session){paused=true;epoch++;revision=(await api('/control',{session_id:session,action:'resync'})).revision;}
clock.set(position,rate);lastPosition=null;resetReadout();paused=before;refreshTimeline();status('已校准；请确保电影与这里同时播放或暂停');
}catch(e){status(e.message);if(session&&paused!==before)await stop();}};
async function stop(){const old=session;session=null;epoch++;paused=false;clock.pause();clearInterval(timer);clearInterval(heartbeat);if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;$('preview').srcObject=null;$('start').disabled=loading;$('pause').disabled=$('stop').disabled=true;$('pause').textContent='暂停陪看';$('frequency').disabled=$('title').disabled=$('subtitle').disabled=false;status('已结束共享');if(old)try{await api('/control',{session_id:old,action:'stop'});}catch(e){status('已停止采集；连接中断，后端会话将在90秒内失效');}}
$('stop').onclick=stop;
$('start').onclick=async()=>{if(session||loading)return;$('start').disabled=true;try{
const position=parsePosition($('position').value),rate=Number($('speed').value);clock.set(position,rate);
stream=await navigator.mediaDevices.getDisplayMedia({video:{frameRate:1},audio:false});
await connect();$('preview').srcObject=stream;await $('preview').play();
const result=await api('/start',{title:$('title').value,frequency:$('frequency').value});session=result.session_id;revision=0;epoch++;sequence=0;paused=false;lastPosition=null;resetReadout();clock.play();
stream.getVideoTracks()[0].onended=stop;$('pause').disabled=$('stop').disabled=false;$('frequency').disabled=$('title').disabled=$('subtitle').disabled=true;
heartbeat=setInterval(async()=>{if(!session)return;try{await api('/control',{session_id:session,action:'heartbeat'});}catch(e){status(e.message);}},15000);
timer=setInterval(observe,15000);status('陪看已开始；请同步播放电影，需要时校准时间');observe();
}catch(e){await stop();status(e.message);}};
$('pause').onclick=async()=>{if(!session)return;const next=!paused;paused=true;epoch++;clock.pause();try{revision=(await api('/control',{session_id:session,action:next?'pause':'resume'})).revision;paused=next;if(!paused)clock.play();$('pause').textContent=paused?'继续陪看':'暂停陪看';status(paused?'已暂停，请同时暂停电影':'继续陪看，请同时播放电影');}catch(e){status(e.message);await stop();}};
async function observe(){if(!session||paused||inFlight)return;const video=$('preview');if(!video.videoWidth)return;
const canvas=document.createElement('canvas'),scale=Math.min(1,1280/video.videoWidth,1280/video.videoHeight);canvas.width=Math.round(video.videoWidth*scale);canvas.height=Math.round(video.videoHeight*scale);canvas.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
const ownEpoch=epoch,position=clock.position(),subtitles=windowCues(cues,position,lastPosition);inFlight=true;try{const result=await api('/observe',{session_id:session,sequence:sequence++,frame:canvas.toDataURL('image/jpeg',.7),position:position,subtitles,timeline_revision:revision});if(ownEpoch!==epoch)return;
if(['commented','silent'].includes(result.status)){showReadout(result);lastPosition=position;$('sentStatus').textContent=`最近分析：${formatPosition(position)} · ${cues.length ? subtitles.length + ' 条导入字幕＋画面' : '画面及其中可辨认的字幕'}`;}
for(const message of result.messages||[]){const item=document.createElement('li');item.textContent=message.content;$('comments').appendChild(item);}status(({preparing:'正在查阅这部电影的介绍和影评，完成后开始理解画面',commented:'左然说了一句，手机上也能看到',silent:'他在安静陪你看',busy:'他正在处理对话，稍后再看',watching:'陪看中',cancelled:'本次观察已取消',paused:'会话已暂停，请结束后重新开始'})[result.status]||'陪看中');
}catch(e){if(ownEpoch===epoch)status(e.message);}finally{inFlight=false;}}
window.addEventListener('pagehide',()=>{if(session){navigator.sendBeacon('/control',new Blob([JSON.stringify({session_id:session,action:'stop'})],{type:'application/json'}));}if(stream)stream.getTracks().forEach(t=>t.stop());});
api('/settings').then(s=>{$('backend').value=s.backend||'';$('connection').open=!s.paired;if(s.paired)status('连接信息已载入，点击开始选择电影窗口');}).catch(e=>status(e.message));
