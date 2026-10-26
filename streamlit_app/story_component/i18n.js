// Display copy and locale formatting never enter audience predicates or model identities.
const StoryI18n={
 locale:null, catalog:null,
 configure(catalog){this.catalog=catalog;if(!catalog.locales.some(x=>x.id===this.locale&&x.status==='ready'))this.locale=catalog.defaultLocale;},
 text(key,params={}){
  const fallback=this.catalog.messages[this.catalog.fallbackLocale];
  const value=this.catalog.messages[this.locale]?.[key]??fallback[key];
  if(typeof value!=='string')throw Error(`Missing story message: ${key}`);
  return value.replace(/\{(\w+)\}/g,(_,name)=>{
   if(params[name]===undefined||params[name]===null)throw Error(`Missing ${name} in story message ${key}`);
   return String(params[name]);
  });
 },
 formatLocale(){return this.catalog.locales.find(x=>x.id===this.locale).formatLocale;},
 number(value,digits=0){return new Intl.NumberFormat(this.formatLocale(),{minimumFractionDigits:digits,maximumFractionDigits:digits}).format(value);},
 percent(value){return new Intl.NumberFormat(this.formatLocale(),{style:'percent',minimumFractionDigits:1,maximumFractionDigits:1}).format(value);},
 currency(value){return new Intl.NumberFormat(this.formatLocale(),{style:'currency',currency:'USD',minimumFractionDigits:2,maximumFractionDigits:2}).format(value);},
 date(value,timestamp=false){
  if(/^\d{8}$/.test(value))value=value.slice(0,4)+'-'+value.slice(4,6)+'-'+value.slice(6,8);
  if(/^\d{4}-\d{2}-\d{2}$/.test(value))value+='T00:00:00Z';
  else if(/^\d{4}-\d{2}-\d{2} /.test(value))value=value.replace(' ','T')+'Z';
  return new Intl.DateTimeFormat(this.formatLocale(),{year:'numeric',month:'short',day:'numeric',timeZone:'UTC',...(timestamp?{hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',timeZoneName:'short'}:{})}).format(new Date(value));
 }
};
const t=(key,params)=>StoryI18n.text(key,params);
const tx=(key,params)=>String(t(key,params)).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number=(value,digits=0)=>StoryI18n.number(value,digits);
const dateLabel=(value,timestamp=false)=>StoryI18n.date(value,timestamp);
function plural(key,count,params={}){
 const category=new Intl.PluralRules(StoryI18n.formatLocale()).select(count);
 const available=StoryI18n.catalog.messages;
 const form=available[StoryI18n.locale]?.[key+'.'+category]??available[StoryI18n.catalog.fallbackLocale][key+'.'+category];
 return t(key+'.'+(typeof form==='string'?category:'other'),{...params,count:number(count)});
}
function setLocale(locale){
 if(!StoryI18n.catalog.locales.some(x=>x.id===locale&&x.status==='ready'))throw Error('Locale is not published');
 const scroll=document.body.scrollTop;
 StoryI18n.locale=locale;render();document.body.scrollTop=scroll;
}
function translateChrome(){
 document.documentElement.lang=StoryI18n.locale;
 document.title=t('chrome.document_title');
 try{window.parent.document.title=document.title;}catch(_){/* Different-origin hosting retains the host title. */}
 document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=t(el.dataset.i18n));
 document.querySelectorAll('[data-i18n-aria]').forEach(el=>el.setAttribute('aria-label',t(el.dataset.i18nAria)));
 document.querySelector('footer').textContent=t('chrome.footer',{date:dateLabel(E.dates.observed)});
 const locales=StoryI18n.catalog.locales.filter(x=>x.status==='ready');
 document.getElementById('language-control').hidden=locales.length<2;
 const select=document.getElementById('language');select.replaceChildren();
 for(const locale of locales){const option=document.createElement('option');option.value=locale.id;option.textContent=locale.label;option.selected=locale.id===StoryI18n.locale;select.append(option);}
 document.getElementById('terms').value=precise?'precise':'plain';
}
