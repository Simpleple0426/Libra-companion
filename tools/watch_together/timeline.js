/* Pure playback-clock and subtitle-window helpers, shared by UI and tests. */
(function(root){
  class PlaybackClock {
    constructor(now=()=>performance.now()){this.now=now;this.value=0;this.rate=1;this.running=false;this.anchor=now();}
    position(){return this.value+(this.running?(this.now()-this.anchor)/1000*this.rate:0);}
    set(value,rate=this.rate){if(!Number.isFinite(value)||value<0||value>360000||!Number.isFinite(rate)||rate<.25||rate>3)throw Error('播放时间或倍速无效');this.value=value;this.rate=rate;this.anchor=this.now();}
    play(){this.set(this.position());this.running=true;}
    pause(){this.set(this.position());this.running=false;}
  }
  function parsePosition(value){const parts=value.trim().split(':');if(!/^(?:\d{1,2}:)?\d{1,3}:\d{2}$/.test(value.trim()))throw Error('请输入 分:秒 或 时:分:秒');const nums=parts.map(Number);if(nums.at(-1)>=60||(nums.length===3&&nums[1]>=60))throw Error('分钟或秒数无效');return nums.reduce((a,b)=>a*60+b,0);}
  function formatPosition(value){value=Math.floor(value);return [Math.floor(value/3600),Math.floor(value/60)%60,value%60].map(n=>String(n).padStart(2,'0')).join(':');}
  function windowCues(cues,position,lastPosition=null){const lower=Math.max(0,position-600,lastPosition===null?position-120:lastPosition);let chosen=cues.filter(c=>c.end<=position&&c.end>lower);let size=0;chosen=chosen.slice(-500).reverse().filter(c=>{size+=c.text.length;return size<=18000;}).reverse();return chosen;}
  const api={PlaybackClock,parsePosition,formatPosition,windowCues};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.WatchTimeline=api;
})(typeof window!=='undefined'?window:globalThis);
