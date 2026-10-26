// Streamlit's v1 component protocol. Only aggregate requests/results cross this boundary.
let pendingQuery=null;
let evidenceUrl='';
function send(type,extra={}){window.parent.postMessage({isStreamlitMessage:true,type,...extra},'*');}
function requestComparison(definition){
 if(pendingQuery)pendingQuery.reject(Error('Superseded comparison'));
 const id=crypto.randomUUID();
 return new Promise((resolve,reject)=>{pendingQuery={id,resolve,reject};send('streamlit:setComponentValue',{value:{id,definition},dataType:'json'});});
}
function sizeFrame(){
 // One scrolling story viewport preserves the approved navigation behavior.
 let height=window.screen.availHeight;
 try{height=window.parent.innerHeight;}catch(_){/* Fallback for different-origin hosting. */}
 send('streamlit:setFrameHeight',{height:Math.max(400,height-24)});
}
window.addEventListener('message',event=>{
 if(event.source!==window.parent||event.data.type!=='streamlit:render')return;
 const args=event.data.args;
 if(!E||JSON.stringify(E.fingerprints)!==JSON.stringify(args.bootstrap.fingerprints)){
  if(E){
   requestId++;page=1;qid='';current=null;draft=null;pending=false;waiting=false;error='';openDetails.clear();
   if(pendingQuery){pendingQuery.reject(Error('Snapshot changed'));pendingQuery=null;}
   URL.revokeObjectURL(evidenceUrl);
  }
  E=args.bootstrap;
  StoryI18n.configure(E.localization);
  evidenceUrl=URL.createObjectURL(new Blob([JSON.stringify(E.methods,null,2)],{type:'application/json'}));
  render();
 }
 const response=args.response;
 if(response&&pendingQuery?.id===response.id){
  const pending=pendingQuery;pendingQuery=null;
  response.error?pending.reject(Error(response.error)):pending.resolve(response.data);
 }
 sizeFrame();
});
window.addEventListener('resize',sizeFrame);
send('streamlit:componentReady',{apiVersion:1});
sizeFrame();
