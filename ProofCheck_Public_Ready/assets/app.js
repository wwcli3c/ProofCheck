'use strict';
const $ = id => document.getElementById(id);
const safe = x => String(x ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = { id:null, session:null, evidence:[], mode:'web', checkId:null, collected:'', streams:[], recorder:null, recorded:[], mediaUrl:null, audio:null, hits:new Set(), shareTokens:[], screenStep:0, screenColors:['#ff0000','#00ff00','#0000ff','#ffffff','#000000','#aaaaaa'] };
const STATUS = {pass:'اجتاز',fail:'مشكلة',not_tested:'لم يُختبر',unavailable:'غير متاح',needs_review:'فحص إضافي'};
function knownSessions(){try{const arr=JSON.parse(localStorage.getItem('proofcheck_history')||'[]');return Array.isArray(arr)?arr.filter(x=>x&&typeof x.id==='string'&&/^[\w-]{20,100}$/.test(x.id)).slice(0,50):[];}catch(_){return [];}}
function recordSession(){
 if(!state.id||!state.session)return;
 const d=state.session.device||{};
 const label=[d.manufacturer,d.model,d.nickname].filter(Boolean).join(' · ').slice(0,95)||'جهاز لم يُسمَّ بعد';
 const arr=knownSessions().filter(x=>x.id!==state.id);
 arr.unshift({id:state.id,label,at:new Date().toISOString()});
 localStorage.setItem('proofcheck_history',JSON.stringify(arr.slice(0,50)));
 updateSessionHistory();
}
function updateSessionHistory(){
 const el=$('sessionHistory');if(!el)return;
 const old=el.value;
 const arr=knownSessions();
 el.replaceChildren();
 const head=new Option(arr.length?'اختر جلسة':'لا توجد جلسات في هذا المتصفح','');el.add(head);
 for(const x of arr)el.add(new Option(`${x.label} (${x.at.slice(0,10)})${x.id===state.id?' • الحالية':''}`,x.id));
 if(arr.some(x=>x.id===old))el.value=old;
}

const CHECKS = [
 {id:'screen', title:'ألوان الشاشة والبكسلات', ico:'▣', desc:'عرض ألوان كاملة والتحقق البصري من البقع والخطوط والبكسلات.'},
 {id:'touch', title:'اللمس / الماوس', ico:'☝', desc:'تغطية 16 منطقة تفاعلية وفحص الاستجابة بشكل يدوي.'},
 {id:'camera', title:'الكاميرا الأمامية والخلفية', ico:'▣', desc:'معاينة فيديو حقيقي بإذن المستخدم؛ ويمكن حفظ لقطة كدليل.'},
 {id:'microphone', title:'الميكروفون والتسجيل', ico:'🎙', desc:'تسجيل صوتي قصير وتشغيله للتحقق السمعي.'},
 {id:'speaker', title:'السماعات والصوت', ico:'♫', desc:'إصدار نغمة فعلية والاستماع لها.'},
 {id:'keyboard', title:'لوحة المفاتيح والأزرار', ico:'⌨', desc:'اختبار الضغط على لوحة المفاتيح وتوثيق الأزرار التي جُربت.'},
 {id:'battery', title:'البطارية والشحن', ico:'▰', desc:'قراءة بيانات الشحن المتاحة؛ صحة البطارية قد لا تكون مكشوفة.'},
 {id:'internet', title:'الاتصال بالخادم', ico:'◉', desc:'قياس طلب شبكة من المتصفح إلى خادم ProofCheck؛ ليس اختبار شبكة خلوية كاملًا.'},
 {id:'cpu', title:'اختبار حسابات المعالج', ico:'⚙', desc:'قياس قصير على جهاز الزائر داخل المتصفح، أو في الوكيل المحلي، دون إثبات سلامة الشريحة.'},
 {id:'memory', title:'اختبار ذاكرة المتصفح', ico:'▤', desc:'تخصيص وقراءة/كتابة 8 MiB في متصفح الزائر؛ لا يفحص سلامة كامل RAM.'},
 {id:'disk', title:'اختبار تخزين المتصفح', ico:'▥', desc:'عبر الإنترنت: كتابة/قراءة بيانات صغيرة في IndexedDB؛ محليًا: ملف مؤقت. لا يكشف حالة SSD.'},
 {id:'storage_health', title:'حالة التخزين / SMART', ico:'◈', desc:'معلومات نظام أو SMART حيث يتوفر العتاد والأداة والتصاريح.'},
 {id:'parts', title:'تتبع القطع والإصلاحات', ico:'♧', desc:'مطابقة إفادات البائع وفواتير القطع؛ لا يوجد إثبات آلي شامل للأصالة.'},
 {id:'buttons', title:'الأزرار والاهتزاز', ico:'⊞', desc:'فحص يدوي للأزرار وتجربة الاهتزاز في الأجهزة التي تدعم واجهة الويب.'},
 {id:'ports', title:'المنافذ والشحن', ico:'⏚', desc:'فحص يدوي لمنافذ الشحن و USB/HDMI والسماعات حسب الجهاز.'}
];
function defaultSession(){return {device:{category:'laptop',manufacturer:'',model:'',serial:'',nickname:'',seller:'',notes:''}, checks:[],repairs:[],browser:{},automated:{},remarks:''};}
const pause = t=>new Promise(r=>setTimeout(r,t));
function toast(s,fail=false){const el=$('toast');el.textContent=s;el.style.borderColor=fail?'#a15460':'#6b9add';el.classList.remove('hidden');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.add('hidden'),4500);}
function notice(s,error=false){$('notice').textContent=s;$('notice').classList.toggle('error',error);}
async function api(path,options={}) {
 const resp = await fetch(path, {cache:'no-store',...options,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})}});
 let payload;
 try{payload=await resp.json();}catch(_){payload={error:'استجابة غير قابلة للقراءة'};}
 if(!resp.ok)throw new Error(payload.error||`HTTP ${resp.status}`);
 return payload;
}
function getCheck(id){return state.session.checks.find(c=>c.id===id);}
function setCheck(id, status, method='user_confirmed', details=''){
 const t=CHECKS.find(c=>c.id===id);if(!t)return;
 const item={id,title:t.title,status,method,details,timestamp:new Date().toISOString()};
 state.session.checks=state.session.checks.filter(x=>x.id!==id).concat(item);render();save().then(()=>loadSession(state.id)).catch(e=>toast(e.message,true));
}
async function save(){if(!state.id)return;await api('/api/sessions/'+state.id,{method:'POST',body:JSON.stringify({data:state.session})});recordSession();}
async function createSession(){const r=await api('/api/sessions',{method:'POST',body:JSON.stringify({data:defaultSession()})});state.id=r.session_id;state.session=r.data;state.evidence=[];state.shareTokens=[];localStorage.setItem('proofcheck_session',state.id);recordSession();leaveWelcome();notice(state.mode==='web'?'جلسة خاصة جديدة محفوظة على خادم ProofCheck؛ لا تشارك رمز جلستك السري.':'جلسة فحص جديدة محفوظة على الكمبيوتر المحلي.');render();await refreshBrowser();}
async function loadSession(id){const r=await api('/api/sessions/'+id);state.id=r.session_id;state.session=r.data;state.evidence=r.evidence;state.shareTokens=JSON.parse(localStorage.getItem('proofcheck_shares_'+state.id)||'[]');localStorage.setItem('proofcheck_session',state.id);recordSession();leaveWelcome();render();notice('الجلسة محفوظة. الفحوصات التي لم تُجرَ تظهر «لم يُختبر».');}
function enterWelcome(){ $('appMain').classList.add('awaiting-session');$('welcomeGate').classList.remove('hidden');notice('الموقع جاهز للفحص. وافق على حفظ بيانات الجلسة لبدء فحص جهازك.'); }
function leaveWelcome(){ $('appMain').classList.remove('awaiting-session');$('welcomeGate').classList.add('hidden'); }
function switchTab(tab){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('selected',b.dataset.tab===tab));document.querySelectorAll('.tab-pane').forEach(p=>p.classList.toggle('hidden',p.id!==`tab-${tab}`));}
function detailLine(key,value){return `<div class="info-line"><span>${safe(key)}</span><b>${safe(value||'غير متاح')}</b></div>`;}
function bytes(n){if(typeof n!=='number'||!Number.isFinite(n))return 'غير متاح';for(let unit of ['B','KiB','MiB','GiB','TiB']){if(n<1024)return `${n.toFixed(unit==='B'?0:1)} ${unit}`;n/=1024;}return n.toFixed(1)+' PiB';}
function renderSystem(d,origin){
 if(!d){$('systemInfo').innerHTML='<div class="muted">لا توجد بيانات نظام مقروءة بعد.</div>';return;}
 if(origin==='native'){
  const b=d.battery||{};const h=d.battery_detail||{};const ident=d.device_identity||{};
  let health= h.health_percent_estimate==null ? 'غير متاح' : h.health_percent_estimate+'% (تقدير نظام)';
  $('systemInfo').innerHTML=[detailLine('النظام',`${d.os||''} ${d.os_release||''}`),detailLine('الشركة والموديل',`${ident.manufacturer||''} ${ident.model||''}`),detailLine('المعالج',d.processor||d.logical_cpu_count+' أنوية منطقية'),detailLine('RAM', bytes(d.memory?.total_bytes)),detailLine('مساحة تخزين متاحة', bytes(d.disk_home?.free_bytes)),detailLine('شحن البطارية',typeof b.percent==='number'?b.percent+'%':'غير متاح'),detailLine('السعة الصحية وفق إفادة النظام',health),detailLine('تاريخ قراءة البيانات',d.collected_at)].join('');
 }else{
  $('systemInfo').innerHTML=[detailLine('نظام المتصفح',d.platform),detailLine('أبعاد الشاشة',d.screen),detailLine('الذاكرة المعلنة بالمتصفح',d.ram),detailLine('شحن البطارية',d.battery),detailLine('الاتصال',d.connection)].join('');
 }
}
function render(){
 if(!state.session)return;
 const d=state.session.device;for(const [id,value] of Object.entries({deviceCategory:d.category,deviceMake:d.manufacturer,deviceModel:d.model,deviceNickname:d.nickname,deviceSerial:d.serial,deviceSeller:d.seller,deviceNotes:d.notes,remarks:state.session.remarks})){const el=$(id);if(el && document.activeElement!==el)el.value=value||'';}
 const checked=state.session.checks;
 $('countDone').textContent=checked.filter(x=>!['not_tested'].includes(x.status)).length+' / '+CHECKS.length;
 $('countPass').textContent=checked.filter(x=>x.status==='pass').length;
 $('countIssue').textContent=checked.filter(x=>['fail','needs_review'].includes(x.status)).length;
 $('countEvidence').textContent=state.evidence.length;
 $('sourceLabel').textContent=state.mode==='desktop'?'تقرير النظام المحلي':'قراءة المتصفح فقط';
 renderSystem(state.session.automated?.device||state.session.browser, state.session.automated?.device?'native':'web');
 $('checkCards').innerHTML=CHECKS.map(t=>{const c=getCheck(t.id);const status=c?.status||'not_tested';return `<article class="test"><div class="test-icon">${t.ico}</div><strong>${safe(t.title)}</strong><p>${safe(t.desc)}</p><div class="bottom"><span class="status ${status}">${STATUS[status]||'لم يُختبر'}</span><button class="ghost" data-open="${t.id}">بدء الاختبار</button></div></article>`;}).join('');
 $('repairsList').innerHTML=state.session.repairs.length ? state.session.repairs.map((r,i)=>`<div class="entry"><div class="entry-title"><strong>${safe(r.part)} · ${r.action==='repair'?'إصلاح':r.action==='replace'?'استبدال':'غير محدد'}</strong><button class="danger" data-removerepair="${i}">حذف</button></div><small>${safe(r.date)} · ${safe(r.provider)}</small><div>${safe(r.notes||'')}</div><small>المرجع: ${safe(r.evidence||'لا يوجد')} · غير متحقق منه خارجيًا</small></div>`).join(''):'<p class="muted">لا توجد إصلاحات مسجلة.</p>';
 $('evidenceList').innerHTML=state.evidence.length?state.evidence.map(e=>`<div class="entry"><div class="entry-title"><strong>${safe(e.filename)}</strong><button class="danger" data-removeevidence="${safe(e.id)}">حذف</button></div><small>${bytes(e.bytes)} · SHA-256: ${safe(e.sha256).slice(0,18)}…</small><a href="/api/evidence/${encodeURIComponent(state.id)}/${encodeURIComponent(e.id)}" target="_blank" rel="noopener" style="color:#9fc7ff">عرض المرفق الخاص</a></div>`).join(''):'<p class="muted">لا توجد مرفقات.</p>';
 $('reportSummary').innerHTML=generateSummary();renderShares();
 const native=state.mode==='desktop';$('scanStorage').disabled=!native;
 $('benchmarkMode').textContent=native?'قياسات محلية للكمبيوتر (نظام التشغيل)':'قياسات قصيرة على جهازك داخل المتصفح';
 $('benchmarkScope').textContent=native?'اختبار الكمبيوتر المحلي يكتب ملفًا مؤقتًا محدودًا ويمسح البيانات بعد الفحص.':'اختبارات CPU وذاكرة JavaScript وIndexedDB تعمل على جهاز الزائر، لا على خادم الموقع. النتائج تقديرية، ولا تتحقق من سلامة العتاد أو أصالة القطع.';
}
function generateSummary(data=state.session,evidence=state.evidence){
 const c=data.checks||[];const ok=c.filter(x=>x.status==='pass').length;const bad=c.filter(x=>x.status==='fail').length;
 const need=c.filter(x=>x.status==='needs_review').length;const notRun=CHECKS.length-c.length;
 return `<div class="entry"><strong>ملخص التغطية:</strong> ناجح ${ok} · مشكلة ${bad} · يحتاج متابعة ${need} · غير مفحوص ${notRun}</div>`+
 `<div class="entry"><strong>الجهاز:</strong> ${safe(data.device?.manufacturer)} ${safe(data.device?.model)} · ${safe(data.device?.category)}<div><small>تقرير تجميع نتائج وليس شهادة أصالة أو ضمانًا لخلو الجهاز من الأعطال.</small></div></div>`+
 `<div class="entry"><strong>سجل الإصلاحات:</strong> ${(data.repairs||[]).length} · <strong>الأدلة:</strong> ${evidence.length} ملفًا <div><small>إفادات الإصلاح غير موثقة خارجيًا ما لم تُرفق وتُراجع مستندات مناسبة.</small></div></div>`+
 c.map(x=>`<div class="entry"><strong>${safe(x.title)}:</strong> ${safe(STATUS[x.status])} <small>الطريقة: ${methodText(x.method)} · ${safe(x.details)}</small></div>`).join('');
}
function methodText(m){return ({measured:'قياس كمبيوتر محلي',browser_measured:'قياس متصفح على جهاز الزائر (غير موثَّق خارجيًا)',os_reported:'بيانات نظام',user_confirmed:'تأكيد المستخدم',unavailable:'لم يتح للنظام'})[m]||'تأكيد المستخدم';}
function renderShares(){ $('sharesList').innerHTML=state.shareTokens.length?state.shareTokens.map(t=>`<div class="entry"><div class="entry-title"><strong>رابط سابق</strong><button class="danger" data-revoke="${safe(t.token)}">إلغاء الرابط</button></div><small>ينتهي ${new Date(t.expires*1000).toLocaleString('ar-SA')}</small></div>`).join(''):'';}
async function refreshBrowser(){
 const b={platform:navigator.platform||'غير معروف',userAgent:navigator.userAgent||'غير معروف',screen:`${window.screen.width} × ${window.screen.height}`,ram:navigator.deviceMemory?`${navigator.deviceMemory} GiB تقريبية`:'غير متاح',battery:'غير متاح',connection:navigator.connection?.effectiveType||'غير متاح'};
 try{if(navigator.getBattery){let x=await navigator.getBattery();b.battery=Math.round(x.level*100)+'% شحن (ليس صحة البطارية)';}}catch(_){}
 state.session.browser=b;await save();render();
}
async function refreshSystem(){
 if(state.mode==='desktop'){
  notice('قراءة معلومات النظام…');const d=await api('/api/system');
  await api('/api/sessions/'+state.id+'/automated',{method:'POST',body:JSON.stringify({field:'device'})});
  await loadSession(state.id);
  notice('تمت قراءة معلومات النظام؛ هذه القيم ليست شهادة بأصالة القطع.');return d;
 }
 await refreshBrowser();toast('تمت قراءة خصائص المتصفح المتاحة');
}
async function storageInfo(){try{
 const s=await api('/api/storage');
 await api('/api/sessions/'+state.id+'/automated',{method:'POST',body:JSON.stringify({field:'storage'})});
 const hasSmart=Array.isArray(s.smartctl) && s.smartctl.length;
 await loadSession(state.id);toast('تم تحديث معلومات التخزين');
 }catch(e){toast(e.message,true);}}
async function benchmarks(tests){
 if(state.mode!=='desktop')return browserBenchmarks(tests);
 ['runBenchmarks','runCpu','runMemory','runDisk'].forEach(id=>$(id).disabled=true);
 $('benchmarkResults').textContent='الفحص يعمل محليًا…';
 try{const result=await api('/api/benchmark',{method:'POST',body:JSON.stringify({tests,session_id:state.id})});
 const lines=[];
 for(const [key,val] of Object.entries(result.results||{})){
  const details=key==='cpu'?`عمليات ${val.operations}، الزمن ${val.elapsed_seconds} ثانية، عدد العمليات/ث ${val.operations_per_second}`:
  key==='memory'?`${bytes(val.bytes_tested)} كتابة/قراءة مختصرة، الزمن ${val.elapsed_seconds} ثانية`:
  val.error?`خطأ: ${val.error}`:`كتابة ${val.write_mib_per_second} MiB/s، قراءة ${val.read_mib_per_second} MiB/s بملف مؤقت ${bytes(val.size_bytes)}`;
  lines.push(detailLine(key==='cpu'?'المعالج':key==='memory'?'الذاكرة':'القرص',details));
 }
 $('benchmarkResults').innerHTML=lines.join('')+`<p class="help">«اجتاز» يعني أن الاختبار القصير اكتمل، وليس أن كل قطعه سليمة أو أنها أصلية.</p>`;
 await loadSession(state.id);toast('اكتملت القياسات القصيرة');
 }catch(e){$('benchmarkResults').textContent='فشل الفحص: '+e.message;toast(e.message,true);}finally{render();}
}
// Browser-side checks: all computation and IndexedDB operations happen on the visitor's device.
function workerMeasure(kind){
 return new Promise((resolve,reject)=>{
  if(!window.Worker)return reject(new Error('Web Workers غير متاحة'));
  let done=false;
  const w=new Worker('/assets/bench-worker.js');
  const timer=setTimeout(()=>{if(done)return;done=true;w.terminate();reject(new Error('انتهت المهلة (15 ثانية)'));},15000);
  const finish=(error,result)=>{if(done)return;done=true;clearTimeout(timer);w.terminate();error?reject(error):resolve(result);};
  w.onerror=e=>finish(new Error(e.message||'تعذّر تشغيل قياس المتصفح'));
  w.onmessage=e=>e.data?.ok?finish(null,e.data):finish(new Error(e.data?.error||'فشل القياس'));
  w.postMessage({kind});
 });
}
function openBenchDB(name){return new Promise((res,rej)=>{
 const r=indexedDB.open(name,1);
 r.onerror=()=>rej(r.error||new Error('IndexedDB unavailable'));
 r.onupgradeneeded=()=>r.result.createObjectStore('test');
 r.onsuccess=()=>res(r.result);
});}
function txDone(tx){return new Promise((res,rej)=>{tx.oncomplete=()=>res();tx.onerror=()=>rej(tx.error||new Error('IndexedDB transaction failed'));tx.onabort=()=>rej(tx.error||new Error('IndexedDB transaction aborted'));});}
async function diskBrowserMeasure(){
 if(!window.indexedDB)throw new Error('IndexedDB غير متاحة أو محظورة في الوضع الخاص');
 const name='proofcheck-benchmark-'+crypto.randomUUID();
 let database=null;
 try{
  database=await openBenchDB(name);
  const buffer=new Uint8Array(2*1024*1024);
  for(let i=0;i<buffer.length;i+=4096)buffer[i]=i&255;
  const start=performance.now();
  let tx=database.transaction('test','readwrite');const written=txDone(tx);tx.objectStore('test').put(buffer,'sample');await written;
  const afterWrite=performance.now();
  tx=database.transaction('test','readonly');const completed=txDone(tx);
  const r=tx.objectStore('test').get('sample');
  const result=await new Promise((res,rej)=>{r.onsuccess=()=>res(r.result);r.onerror=()=>rej(r.error);});
  await completed;
  const afterRead=performance.now();
  if(!(result instanceof Uint8Array)||result.length!==buffer.length)throw new Error('فشل التحقق من قراءة بيانات الاختبار');
  return {kind:'disk',bytes:buffer.length,writeMs:+(afterWrite-start).toFixed(2),readMs:+(afterRead-afterWrite).toFixed(2)};
 } finally {
  if(database)database.close();
  try{indexedDB.deleteDatabase(name);}catch(_){}
 }
}
async function browserBenchmarks(tests){
 const buttons=['runBenchmarks','runCpu','runMemory','runDisk'];
 buttons.forEach(id=>$(id).disabled=true);
 const lines=[];
 $('benchmarkResults').textContent='تجري الآن قياسات على جهازك داخل المتصفح…';
 try {
  for(const kind of tests){
   try{
    const r=kind==='disk'?await diskBrowserMeasure():await workerMeasure(kind);
    const details=kind==='cpu'?`JavaScript: ${r.iterations.toLocaleString()} تكرار خلال ${r.ms} ms (مجموع تحقق ${r.checksum}). لا يقيس صحة المعالج.`:
      kind==='memory'?`ذاكرة متصفح ${bytes(r.bytes)}: كتابة وقراءة مختصرة خلال ${r.ms} ms، ليست فحص RAM كاملًا.`:
      `IndexedDB: ${bytes(r.bytes)}، وقت الكتابة ${r.writeMs} ms والقراءة ${r.readMs} ms. لا يقيس سرعة القرص الفيزيائية.`;
    lines.push(detailLine(kind==='cpu'?'معالج المتصفح':kind==='memory'?'ذاكرة المتصفح':'تخزين المتصفح',details));
    const t=CHECKS.find(t=>t.id===kind);
    state.session.checks=state.session.checks.filter(x=>x.id!==kind).concat({id:kind,title:t.title,status:'pass',method:'browser_measured',details,timestamp:new Date().toISOString()});
   }catch(err){
    lines.push(detailLine(kind,'غير متاح: '+err.message));
    const t=CHECKS.find(t=>t.id===kind);
    state.session.checks=state.session.checks.filter(x=>x.id!==kind).concat({id:kind,title:t.title,status:'unavailable',method:'unavailable',details:String(err.message).slice(0,400),timestamp:new Date().toISOString()});
   }
  }
  await save();await loadSession(state.id);
  $('benchmarkResults').innerHTML=lines.join('')+'<p class="help">القياسات محلية للمتصفح، وليست نتيجة معملية أو شهادة على سلامة القطع. لا تُرسل بيانات الاختبار الخام إلى الخادم، بل ملخصها فقط عند حفظ الجلسة.</p>';
  toast('اكتملت قياسات المتصفح وحُفظت في جلستك');
 } catch(err){$('benchmarkResults').textContent='تعذر حفظ النتائج: '+err.message;toast(err.message,true);}
 finally{buttons.forEach(id=>$(id).disabled=false);}
}
async function captureEvidence(file){if(!state.id)throw new Error('لا توجد جلسة');if(file.size>2*1024*1024)throw new Error(`${file.name}: الحد 2 ميجابايت`);
 const b64=await new Promise((resolve,reject)=>{const rd=new FileReader();rd.onload=()=>resolve(String(rd.result).split(',')[1]);rd.onerror=()=>reject(new Error('فشل قراءة الملف'));rd.readAsDataURL(file);});
 const e=await api('/api/sessions/'+state.id+'/evidence',{method:'POST',body:JSON.stringify({filename:file.name,data:b64})});state.evidence.push(e);render();return e;
}
function closeModal(){stopMedia();$('testModal').classList.add('hidden');state.checkId=null;state.collected='';}
function stopMedia(){for(const s of state.streams){try{s.getTracks().forEach(t=>t.stop());}catch(_){}}state.streams=[];if(state.recorder?.state==='recording'){try{state.recorder.stop();}catch(_){}}state.recorder=null;if(state.audio){try{state.audio.close();}catch(_){}}state.audio=null;}
function dialog(id){
 const c=CHECKS.find(x=>x.id===id);if(!c)return;state.checkId=id;state.collected='';state.hits=new Set();$('modalTitle').textContent=c.title;$('modalDesc').textContent=c.desc;$('modalBody').innerHTML='';$('testModal').classList.remove('hidden');
 if(id==='screen'){$('modalBody').innerHTML='<div class="tool">سيتم فتح شاشة ملونة بالتتابع. لاحظ وجود خطوط أو بقع أو نقاط لا تتغير.<p><button class="primary" id="startScreen">بدء اختبار الألوان</button></p></div>';$('startScreen').onclick=startScreen;}
 else if(id==='touch'){const body=$('modalBody');body.innerHTML=`<div class="tool">مرّر إصبعك أو الماوس على كل الخانات وتأكد أن الاستجابة سليمة.<div class="touch-grid" id="touchGrid">${Array.from({length:16},(_,i)=>`<div class="touch-cell" data-cell="${i}">${i+1}</div>`).join('')}</div><span id="touchProgress">0 / 16</span></div>`;const touch=e=>{if(e.cancelable)e.preventDefault();let el=document.elementFromPoint(e.clientX,e.clientY);if(el?.dataset?.cell!==undefined){state.hits.add(el.dataset.cell);el.classList.add('hit');$('touchProgress').textContent=state.hits.size+' / 16';state.collected=`استجاب ${state.hits.size} من 16 خانة في اختبار إدخال يدوي`;}};const grid=$('touchGrid');grid.addEventListener('pointerdown',touch);grid.addEventListener('pointermove',e=>{if(e.buttons||e.pointerType==='touch')touch(e);});}
 else if(id==='camera'){$('modalBody').innerHTML='<div class="tool"><video class="camera" id="cameraFeed" autoplay playsinline muted></video><div class="actions"><button class="primary" id="cameraFront">الأمامية</button><button class="ghost" id="cameraBack">الخلفية / الرئيسية</button><button class="ghost" id="cameraSnap">حفظ لقطة كدليل</button></div><p id="cameraNote" class="muted">سيتطلب تشغيل الكاميرا إذنًا من المتصفح و HTTPS أو localhost.</p></div>';$('cameraFront').onclick=()=>camera('user');$('cameraBack').onclick=()=>camera('environment');$('cameraSnap').onclick=cameraSnapshot;}
 else if(id==='microphone'){$('modalBody').innerHTML='<div class="tool"><p>سجّل كلامًا قصيرًا ثم استمع إليه. لا يُحفظ التسجيل على الخادم تلقائيًا.</p><div class="actions"><button id="micStart" class="primary">بدء التسجيل</button><button id="micStop" class="ghost">إيقاف</button></div><p id="micInfo">لم يبدأ التسجيل.</p><audio class="player" id="micPlayback" controls></audio></div>';$('micStart').onclick=micStart;$('micStop').onclick=micStop;}
 else if(id==='speaker'){$('modalBody').innerHTML='<div class="tool"><p>اضغط واستمع إلى نغمة قصيرة. اخفض مستوى الصوت أولًا.</p><button class="primary" id="playTone">تشغيل النغمة</button></div>';$('playTone').onclick=playTone;}
 else if(id==='keyboard'){$('modalBody').innerHTML='<div class="tool"><label>اضغط الأزرار واكتب هنا<input id="keyInput" autocomplete="off" placeholder="جرّب الأحرف والأرقام والمسافة و Enter"></label><p id="keyStats">0 زر مختلف</p></div>';const keys=new Set();$('keyInput').onkeydown=e=>{keys.add(e.code);state.collected=`تم التقاط ${keys.size} زر مختلف: ${[...keys].slice(0,25).join(', ')}`;$('keyStats').textContent=keys.size+' زر مختلف';};}
 else if(id==='battery'){$('modalBody').innerHTML='<div class="tool"><button class="primary" id="batteryRead">قراءة البطارية المتاحة</button><div id="batteryData" class="info-list">لم تُقرأ بعد.</div></div>';$('batteryRead').onclick=readBattery;}
 else if(id==='internet'){$('modalBody').innerHTML='<div class="tool"><button class="primary" id="testPing">إجراء اتصال قياسي</button><p id="pingResult"></p></div>';$('testPing').onclick=ping;}
 else if(['cpu','memory','disk'].includes(id)){$('modalBody').innerHTML='<div class="tool"><button class="primary" id="runOneTest">تشغيل قياس على جهازي</button><p class="muted">الفحص يعمل في متصفحك عند فتح الرابط العام، أو عبر أداة النظام عند تشغيل نسخة الكمبيوتر المحلية. النتيجة ليست إثبات سلامة العتاد.</p></div>';$('runOneTest').onclick=async()=>{closeModal();switchTab('tests');await benchmarks([id]);};}
 else if(id==='storage_health'){$('modalBody').innerHTML='<div class="tool"><button id="doStorage" class="primary">قراءة SMART/OS</button><p>يعتمد على دعم نظام التشغيل و smartctl وتصاريح قراءة القرص.</p></div>';$('doStorage').disabled=state.mode!=='desktop';$('doStorage').onclick=async()=>{closeModal();await storageInfo();};}
 else if(id==='buttons'){$('modalBody').innerHTML='<div class="tool"><button id="vibrateNow" class="ghost">اختبار الاهتزاز عند توفره</button><p>اختبر زر الطاقة ورفع وخفض الصوت فعليًا خارج المتصفح ثم اختر نتيجة الفحص اليدوية.</p></div>';$('vibrateNow').onclick=()=>{let yes=!!navigator.vibrate?.(200);state.collected=yes?'تم إرسال طلب اهتزاز؛ النتيجة تتطلب تأكيد المستخدم':'واجهة الاهتزاز غير متاحة في هذا المتصفح';toast(state.collected);};}
 else if(id==='parts'){$('modalBody').innerHTML='<div class="tool">سجّل الفواتير وبيانات الإصلاح في تبويب «الإصلاحات والأدلة». سجل الفواتير لا يثبت هوية القطعة إلا بعد تحقق فني مستقل.</div>';}
 else {$('modalBody').innerHTML='<div class="tool">اختبر المنفذ باستخدام كابل أو ملحق تعرف أنه يعمل. ظهور الشحن لا يثبت سلامة كل وظائف المنفذ أو أصالة القطعة.</div>';}
}
function setScreenStep(n){const overlay=$('screenOverlay');for(let i=0;i<6;i++)overlay.classList.toggle('color-step-'+i,i===n);}
function startScreen(){state.screenStep=0;setScreenStep(0);$('screenOverlay').classList.remove('hidden');$('screenOverlay').focus();}
function advanceScreen(){state.screenStep++;if(state.screenStep>=state.screenColors.length){$('screenOverlay').classList.add('hidden');state.collected='عُرضت 6 ألوان على الشاشة؛ التأكد من البكسلات بصري وبشهادة المستخدم';return;}setScreenStep(state.screenStep);}
async function camera(facingMode){stopMedia();try{let stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:facingMode}},audio:false});state.streams.push(stream);$('cameraFeed').srcObject=stream;const t=stream.getVideoTracks()[0];state.collected=`تدفق فيديو من كاميرا: ${t.label||facingMode}، ولم تُفحص جودة الحساس آليًا`;$('cameraNote').textContent='ظهرت المعاينة. افحص وضوح الصورة والتركيز والإضاءة يدويًا.';}catch(e){$('cameraNote').textContent='الكاميرا غير متاحة: '+e.message;toast('إذن الكاميرا/HTTPS مطلوب أو الجهاز لا يحتوي عليها',true);}}
async function cameraSnapshot(){const vid=$('cameraFeed');if(!vid?.videoWidth)return toast('شغّل الكاميرا أولًا',true);const cv=document.createElement('canvas');const scale=Math.min(1,1300/vid.videoWidth);cv.width=Math.round(vid.videoWidth*scale);cv.height=Math.round(vid.videoHeight*scale);cv.getContext('2d').drawImage(vid,0,0,cv.width,cv.height);cv.toBlob(async blob=>{try{const f=new File([blob],`camera-${Date.now()}.jpg`,{type:'image/jpeg'});await captureEvidence(f);toast('تم حفظ لقطة الكاميرا كدليل في الجلسة');}catch(e){toast(e.message,true);}},'image/jpeg',.8);}
async function micStart(){stopMedia();try{if(!window.MediaRecorder)throw new Error('ميزة التسجيل غير مدعومة');const stream=await navigator.mediaDevices.getUserMedia({audio:true});state.streams.push(stream);state.recorded=[];let r=new MediaRecorder(stream);state.recorder=r;r.ondataavailable=e=>{if(e.data.size)state.recorded.push(e.data);};r.onstop=()=>{if(!state.recorded.length)return;if(state.mediaUrl)URL.revokeObjectURL(state.mediaUrl);const blob=new Blob(state.recorded,{type:r.mimeType||'audio/webm'});state.mediaUrl=URL.createObjectURL(blob);const el=$('micPlayback');if(el)el.src=state.mediaUrl;state.collected=`تم تسجيل مقطع صوتي ${Math.round(blob.size/1024)} KB، تأكيد وضوح الصوت يعتمد على استماع المستخدم`;const msg=$('micInfo');if(msg)msg.textContent='اكتمل التسجيل. استمع إليه قبل تحديد نتيجة الاختبار.';};r.start();$('micInfo').textContent='التسجيل جارٍ…';}catch(e){$('micInfo').textContent='فشل تشغيل الميكروفون: '+e.message;}}
function micStop(){if(state.recorder?.state==='recording'){state.recorder.stop();state.streams.forEach(s=>s.getTracks().forEach(t=>t.stop()));state.streams=[];}}
async function playTone(){try{const AudioC=window.AudioContext||window.webkitAudioContext;if(!AudioC)throw new Error('واجهة الصوت غير متاحة');const ctx=new AudioC();state.audio=ctx;await ctx.resume();const osc=ctx.createOscillator();const gain=ctx.createGain();osc.type='sine';osc.frequency.setValueAtTime(660,ctx.currentTime);gain.gain.setValueAtTime(.05,ctx.currentTime);gain.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+.65);osc.connect(gain);gain.connect(ctx.destination);osc.start();osc.stop(ctx.currentTime+.67);osc.onended=()=>ctx.close().catch(()=>{});state.collected='تم إصدار نغمة 660Hz لمدة 0.65 ثانية؛ تحديد سماعها يحتاج تأكيد المستخدم';toast('إذا سمعت النغمة اضغط «اجتاز»');}catch(e){toast(e.message,true);}}
async function readBattery(){let msg='متصفحك لا يتيح قراءة مستوى البطارية';try{if(navigator.getBattery){const b=await navigator.getBattery();msg=`مستوى الشحن ${Math.round(b.level*100)}%، بالشاحن: ${b.charging?'نعم':'لا'}؛ صحة البطارية غير مقاسة`;state.collected=msg;}else if(state.session.automated?.device?.battery){msg=JSON.stringify(state.session.automated.device.battery);state.collected='إفادة نظام عن الشحن: '+msg.slice(0,250);}}catch(e){msg=e.message;}$('batteryData').textContent=msg;}
async function ping(){const start=performance.now();try{const r=await api('/api/status');let ms=(performance.now()-start).toFixed(1);state.collected=`زمن استجابة خادم ProofCheck = ${ms} مللي ثانية، لا يقيس الاتصال الخارجي أو الشبكة الخلوية`;$('pingResult').textContent=state.collected;}catch(e){$('pingResult').textContent=e.message;}}
function collectDeviceForm(){const d=state.session.device;Object.assign(d,{category:$('deviceCategory').value,manufacturer:$('deviceMake').value.trim(),model:$('deviceModel').value.trim(),nickname:$('deviceNickname').value.trim(),serial:$('deviceSerial').value.trim(),seller:$('deviceSeller').value.trim(),notes:$('deviceNotes').value.trim()});}
function reportObject(){return {app:'ProofCheck',version:'1.1',created:new Date().toISOString(),data:state.session,evidence:state.evidence,scope:'Factual tests, OS telemetry and self-reported repairs; no universal originality certification'};}
function downloadJson(){const b=new Blob([JSON.stringify(reportObject(),null,2)],{type:'application/json'});const url=URL.createObjectURL(b);const a=document.createElement('a');a.href=url;a.download=`ProofCheck-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function publicView(report){$('appMain').classList.add('hidden');const el=$('publicReport');el.classList.remove('hidden');const d=report.data||{};const evidence=report.evidence||[];
 el.innerHTML=`<div class="public-head"><h1>ProofCheck · تقرير فحص جهاز</h1><p class="muted">تقرير للعرض فقط · مُنشأ في ${safe(report.created)}</p></div>
 <section class="box"><h2>بيانات الجهاز</h2>${detailLine('نوع الجهاز',d.device?.category)}${detailLine('الشركة',d.device?.manufacturer)}${detailLine('الموديل',d.device?.model)}${detailLine('الرقم التسلسلي','محجوب للخصوصية')}</section>
 <section class="box"><h2>نتائج الفحص</h2><table><thead><tr><th>الاختبار</th><th>النتيجة</th><th>الطريقة</th><th>الملاحظات</th></tr></thead><tbody>${(d.checks||[]).map(c=>`<tr><td>${safe(c.title)}</td><td>${safe(STATUS[c.status])}</td><td>${safe(methodText(c.method))}</td><td>${safe(c.details)}</td></tr>`).join('')}</tbody></table><p class="small">الاختبارات غير المدرجة لم تُنفّذ. نجاح الاختبار لا يعني ثبوت أصالة القطعة.</p></section>
 <section class="box"><h2>الإصلاحات المدخلة</h2>${(d.repairs||[]).map(r=>`<div class="entry"><strong>${safe(r.part)}</strong> · ${safe(r.action)} · ${safe(r.date)}<div>${safe(r.provider)} · ${safe(r.notes)}</div><small>إفادة من المستخدم، غير متحقق منها خارجيًا</small></div>`).join('')||'لا يوجد سجل'}</section>
 <section class="box"><h2>المرفقات المسجلة (ملفات غير عامة)</h2>${evidence.map(e=>`<div class="entry">${safe(e.filename)} · SHA-256: <small>${safe(e.sha256)}</small></div>`).join('')||'لا يوجد'}</section>
 <section class="box"><h2>التقييم النهائي</h2><p>${safe(d.remarks||'لا توجد ملاحظات إضافية')}</p><p class="small">لا يُعد التقرير ضمانًا فنيًا أو إثباتًا قاطعًا للاستبدال أو أصالة القطع.</p><button class="primary" id="printPublic">طباعة / PDF</button></section>`;
 $('printPublic').onclick=()=>window.print();
}
async function init(){
 try{
  const status=await api('/api/status');state.mode=status.mode;$('envLabel').textContent=status.local_inspector?'وضع فحص الكمبيوتر المحلي':'وضع الفحوصات عبر المتصفح';
  if(location.pathname.startsWith('/report/')){
   const token=location.pathname.split('/')[2];const r=await api('/api/share/'+token);publicView(r);return;
  }
  const previous=localStorage.getItem('proofcheck_session');if(previous){try{await loadSession(previous);}catch(_){localStorage.removeItem('proofcheck_session');if(state.mode==='web')enterWelcome();else await createSession();}}else if(state.mode==='web')enterWelcome();else await createSession();
  if(state.id)await refreshBrowser();
 }catch(e){notice('تعذر بدء الخدمة: '+e.message,true);if(location.pathname.startsWith('/report/')){$('appMain').classList.remove('hidden');}}
}
// All state-changing actions occur only on direct interaction.
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>switchTab(b.dataset.tab));
$('acceptStorage').onchange=()=>{$('startScan').disabled=!$('acceptStorage').checked;};
$('startScan').onclick=()=>createSession().catch(e=>toast('فشل بدء الجلسة: '+e.message,true));
$('copySessionID').onclick=()=>navigator.clipboard?.writeText(state.id||'').then(()=>toast('تم نسخ رمز الجلسة الخاص؛ احتفظ به في مكان آمن')).catch(()=>toast('تعذر النسخ. استخدم متصفحًا يدعم الحافظة',true));
$('openHistory').onclick=async()=>{const id=$('sessionHistory').value;if(!id)return toast('اختر جلسة أولًا',true);try{await loadSession(id);toast('تم فتح جلسة الفحص');}catch(e){toast('تعذّر فتح الجلسة: '+e.message,true);}};
$('openByCode').onclick=async()=>{const id=$('sessionCode').value.trim();if(!/^[\w-]{20,100}$/.test(id))return toast('أدخل رمز جلسة صالحًا',true);try{await loadSession(id);$('sessionCode').value='';toast('تم استرداد جلسة الفحص');}catch(e){toast('لم يتم العثور على الجلسة أو تعذر الاتصال',true);}};
$('deviceForm').onsubmit=async e=>{e.preventDefault();collectDeviceForm();try{await save();render();toast('تم حفظ بيانات الجهاز');}catch(x){toast(x.message,true);}};
$('repairForm').onsubmit=async e=>{e.preventDefault();const r={part:$('repairPart').value.trim(),action:$('repairAction').value,date:$('repairDate').value,provider:$('repairProvider').value.trim(),evidence:$('repairEvidence').value.trim(),notes:$('repairNotes').value.trim(),verified:false};if(!r.part)return;state.session.repairs.push(r);try{await save();$('repairForm').reset();render();toast('أُضيف الإصلاح دون اعتباره متحققًا منه');}catch(x){toast(x.message,true);}};
$('evidenceInput').onchange=async e=>{for(const f of [...e.target.files]){try{await captureEvidence(f);toast('تم إرفاق '+f.name);}catch(x){toast(x.message,true);}}e.target.value='';};
$('scanSystem').onclick=()=>refreshSystem().catch(e=>toast(e.message,true));$('scanStorage').onclick=()=>storageInfo();
$('runBenchmarks').onclick=()=>benchmarks(['cpu','memory','disk']);$('runCpu').onclick=()=>benchmarks(['cpu']);$('runMemory').onclick=()=>benchmarks(['memory']);$('runDisk').onclick=()=>benchmarks(['disk']);
$('newSession').onclick=async()=>{if(confirm('إنشاء جلسة جديدة؟ الجلسة الحالية تبقى على الخادم ويمكنك العودة إليها إذا احتفظت بمعرّفها.'))await createSession().catch(e=>toast(e.message,true));};
$('saveReport').onclick=async()=>{state.session.remarks=$('remarks').value;try{await save();render();toast('تم حفظ التقييم');}catch(e){toast(e.message,true);}};
$('jsonReport').onclick=downloadJson;$('printReport').onclick=()=>{state.session.remarks=$('remarks').value;save().then(()=>window.print()).catch(e=>toast(e.message,true));};
$('createShare').onclick=async()=>{try{state.session.remarks=$('remarks').value;await save();const r=await api('/api/sessions/'+state.id+'/share',{method:'POST',body:JSON.stringify({days:Number($('shareDays').value)})});const url=location.origin+r.path;state.shareTokens.push({token:r.token,expires:r.expires_epoch});localStorage.setItem('proofcheck_shares_'+state.id,JSON.stringify(state.shareTokens));$('shareOutput').innerHTML=`<div class="entry">رابط التقرير: <a href="${safe(url)}" target="_blank" rel="noopener">${safe(url)}</a><div class="actions"><button id="copyShare" class="ghost">نسخ الرابط</button></div><small>رابط التقرير متاح لكل من يملكه إذا كان الموقع منشورًا على HTTPS عام. لا تشاركه إلا مع من تثق بهم.</small></div>`;$('copyShare').onclick=()=>navigator.clipboard?.writeText(url).then(()=>toast('تم نسخ الرابط')).catch(()=>toast('انسخ الرابط يدويًا'));renderShares();toast('تم إنشاء نسخة تقرير دون الرقم التسلسلي');}catch(e){toast(e.message,true);}};
$('deleteSession').onclick=async()=>{if(!confirm('هل تريد حذف الجلسة وكل ملفاتها وروابطها نهائيًا من الخادم الحالي؟'))return;try{await api('/api/sessions/'+state.id,{method:'DELETE'});localStorage.removeItem('proofcheck_session');localStorage.removeItem('proofcheck_shares_'+state.id);localStorage.setItem('proofcheck_history',JSON.stringify(knownSessions().filter(x=>x.id!==state.id)));await createSession();toast('حُذفت الجلسة السابقة');}catch(e){toast(e.message,true);}};
$('checkCards').onclick=e=>{const btn=e.target.closest('[data-open]');if(btn)dialog(btn.dataset.open);};
$('repairsList').onclick=async e=>{const btn=e.target.closest('[data-removerepair]');if(!btn)return;state.session.repairs.splice(Number(btn.dataset.removerepair),1);await save();render();};
$('evidenceList').onclick=async e=>{const btn=e.target.closest('[data-removeevidence]');if(!btn)return;try{await api('/api/evidence/'+state.id+'/'+btn.dataset.removeevidence,{method:'DELETE'});state.evidence=state.evidence.filter(x=>x.id!==btn.dataset.removeevidence);render();}catch(e){toast(e.message,true);}};
$('sharesList').onclick=async e=>{const btn=e.target.closest('[data-revoke]');if(!btn)return;try{await api('/api/sessions/'+state.id+'/shares/'+btn.dataset.revoke,{method:'DELETE'});state.shareTokens=state.shareTokens.filter(x=>x.token!==btn.dataset.revoke);localStorage.setItem('proofcheck_shares_'+state.id,JSON.stringify(state.shareTokens));renderShares();toast('أُلغي رابط التقرير');}catch(e){toast(e.message,true);}};
$('closeModal').onclick=closeModal;
$('testModal').onclick=e=>{if(e.target===$('testModal'))closeModal();const btn=e.target.closest('[data-mark]');if(!btn||!state.checkId)return;const id=state.checkId;let details=state.collected||'النتيجة مؤكدة يدويًا بواسطة من استخدم الجهاز';let method=btn.dataset.mark==='unavailable'?'unavailable':'user_confirmed';
 if(['cpu','memory','disk'].includes(id)&&state.collected==='')details='هذه إفادة يدوية؛ يمكنك تشغيل قياس المتصفح من تبويب الفحوصات';
 setCheck(id,btn.dataset.mark,method,details);closeModal();toast('حُفظت نتيجة الفحص');};
$('screenOverlay').onclick=advanceScreen;
document.addEventListener('keydown',e=>{if(e.key==='Escape'){$('screenOverlay').classList.add('hidden');if(!$('testModal').classList.contains('hidden'))closeModal();}else if(!$('screenOverlay').classList.contains('hidden') && (e.key==='Enter'||e.key===' ')){e.preventDefault();advanceScreen();}});
window.addEventListener('beforeunload',stopMedia);
if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(()=>{});
init();
