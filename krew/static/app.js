"use strict";
/* KREW Control Center. No third-party frontend dependencies. */
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try {tg.ready();tg.expand()} catch (_) {} }
const preview = new URLSearchParams(location.search).has("preview");
const initData = tg ? (tg.initData || "") : "";
const app = {
  chat: null, page:"overview", chats:[], renderController:null,
  demo: {
    chats:[{chat_id:-100123456789,title:"KREW Community"},{chat_id:-100987654321,title:"Creative Lab"}],
    stats:{members:1284,messages:18436,warnings:37,reports:3,actions:42},
    settings:{antispam:true,antilinks:false,welcome:true,fun:true,levels:true,captcha:true,antiforward:false,antiraid:true,warn_limit:3,rules:"Будьте вежливы. Без спама, рекламы и оскорблений.",welcome_text:"Привет, {user}!",antimentions:false,anticaps:false,mention_limit:5},
    reports:[{id:105,reporter_id:3012,target_id:9981,target_message_id:443,created:Math.floor(Date.now()/1000)-3600},{id:106,reporter_id:3018,target_id:9983,target_message_id:452,created:Math.floor(Date.now()/1000)-3600},{id:107,reporter_id:3017,target_id:9985,target_message_id:463,created:Math.floor(Date.now()/1000)-3600}],
    recent:[{action:"warn",target_id:9981,timestamp:Math.floor(Date.now()/1000)-3600},{action:"captcha_timeout",target_id:9901,timestamp:Math.floor(Date.now()/1000)-10800},{action:"mute",target_id:1001,timestamp:Math.floor(Date.now()/1000)-25600}]
  }
};
const content=document.getElementById("content");
function el(tag,cls,txt) { const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=String(txt);return n; }
function append(parent,...children){for(const child of children)if(child)parent.append(child);return parent;}
function p(text,cls="muted tiny"){return el("p",cls,text)}
function fmt(n){return Number(n||0).toLocaleString("ru-RU")}
let notificationTimeout;
function notify(message,error=false){
  const n=document.getElementById("notice");
  clearTimeout(notificationTimeout);
  n.hidden=false;n.className="notice"+(error?" error":"");
  n.textContent=message;
  notificationTimeout=setTimeout(()=>{n.hidden=true},6500);
}
function silence(){clearTimeout(notificationTimeout);document.getElementById("notice").hidden=true}
function haptic(){try{tg?.HapticFeedback?.impactOccurred("light")}catch(_){}}
function navigate(page){
  if(!["overview","settings","reports","analytics","rulesets","community","audit"].includes(page))return;
  app.page=page;haptic();closeMore();refresh();
  if(window.innerWidth<=640)window.scrollTo({top:0,behavior:"smooth"});
}
function closeMore(){
  const menu=document.getElementById("more-menu");
  menu.hidden=true;
  document.getElementById("more-button").setAttribute("aria-expanded","false");
}
function toggleMore(){
  const menu=document.getElementById("more-menu");menu.hidden=!menu.hidden;
  document.getElementById("more-button").setAttribute("aria-expanded",String(!menu.hidden));
  haptic();
}
function loadingSkeleton(){
  const shell=el("div","loading-shell");
  const row=el("div","skeleton-row");
  for(let i=0;i<4;i++)row.append(el("div","skeleton"));
  const panel=el("div","skeleton skeleton-panel");
  shell.append(row,panel);
  return shell;
}
function active(controller){
  return !!controller && controller===app.renderController && !controller.signal.aborted;
}
function restoredChat(){try{return Number(sessionStorage.getItem("krew-active-chat"))}catch(_){return NaN}}
function rememberChat(chat){try{sessionStorage.setItem("krew-active-chat",String(chat))}catch(_){}}
function panel(title,sub){const n=el("div","panel"),head=el("div","panel-head");append(head,el("h2","",title),sub?el("span","muted tiny",sub):null);n.append(head);return n}
function empty(msg){return el("div","empty",msg)}
async function api(path,method="GET",payload){
  if(preview)return fake(path,method,payload);
  if(!initData)throw Error("Откройте панель через Telegram. В браузере доступен демонстрационный режим ?preview=1.");
  const options={
    method,
    headers:{"Authorization":"tma "+initData,...(payload!==undefined?{"Content-Type":"application/json"}:{})},
    body:payload!==undefined?JSON.stringify(payload):undefined,
    cache:"no-store"
  };
  if(method==="GET" && app.renderController)options.signal=app.renderController.signal;
  let response;
  try{response=await fetch(path,options)}
  catch(error){
    if(error.name==="AbortError")throw error;
    throw Error("Нет соединения с KREW. Проверь Cloudflare и подключение к интернету.");
  }
  let data;
  try{data=await response.json()}
  catch(_){throw Error("Сервер KREW ответил некорректно. Обнови страницу.")}
  if(!response.ok)throw Error(typeof data.error==="string"?data.error:"Ошибка сервера KREW");
  return data;
}
function fake(path,method,payload){
  const d=app.demo;
  if(path==="/api/chats")return {chats:d.chats};
  if(path.endsWith("/overview"))return {stats:d.stats,chat:d.chats[0],recent:d.recent};
  if(path.endsWith("/settings")){if(method==="PATCH")d.settings[payload.field]=payload.value;return {settings:{...d.settings}}}
  if(path.endsWith("/reports"))return {reports:d.reports,history:d.history||[]};
  if(path.endsWith("/reject")||path.endsWith("/close")||path.endsWith("/warn")){
    const id=Number((path.match(/reports\/(\d+)\//)||[])[1]);
    const item=d.reports.find(r=>r.id===id);
    if(!item)throw Error("Жалоба уже рассмотрена");
    const status=path.endsWith("/reject")?"rejected":(path.endsWith("/warn")?"warned":"closed");
    d.reports=d.reports.filter(r=>r.id!==id);d.history=d.history||[];
    d.history.unshift({...item,status,decision_reason:payload?.reason||"Нарушение подтверждено модератором",notification_status:"sent",resolved_at:Math.floor(Date.now()/1000)});
    return {status,notification_status:"sent",warning_recorded:status==="warned"};
  }
  if(path.endsWith("/analytics"))return {timeline:Array.from({length:14},(_,i)=>({day:new Date(Date.now()-(13-i)*86400000).toISOString().slice(0,10),messages:Math.round(90+Math.sin(i*1.8)*55+(i*19)%38),joins:6,actions:i%3})),stats:d.stats,top:[{name:"Alex",xp:1240,messages:234},{name:"Mira",xp:1120,messages:210}]};
  if(path.endsWith("/community"))return {community:{active_today:38,claimed_today:12,thanks_today:9,mission_goal:5,mission_reward:35,top_reputation:[{user_id:101,name:"Мира",reputation:18},{user_id:102,name:"Алексей",reputation:13},{user_id:103,name:"Саша",reputation:9}]}};
  if(path.endsWith("/audit"))return {audit:[{field:"captcha",old_value:"0",new_value:"1",actor_id:123,created:Math.floor(Date.now()/1000)-3600},{field:"antiraid",old_value:"0",new_value:"1",actor_id:123,created:Math.floor(Date.now()/1000)-3600}],recent:d.recent};
  if(path.endsWith("/rulesets"))return {words:d.words||["спам","оскорбление"],domains:d.domains||["youtube.com"]};
  if(path.endsWith("/words")||path.endsWith("/domains")) {const key=path.endsWith("/words")?"words":"domains";d[key]=d[key]|| (key==="words"?["спам","оскорбление"]:["youtube.com"]);if(payload.action==="add")d[key].push(payload.value);else d[key]=d[key].filter(v=>v!==payload.value);return {words:d.words||[],domains:d.domains||[]}}
  throw Error("Недоступно в демо")
}

function confirmAction(title,detail){
  return new Promise(resolve=>{
    const overlay=el("div","confirm-overlay");
    const dialog=el("div","confirm-card");
    overlay.setAttribute("role","presentation");
    dialog.setAttribute("role","alertdialog");
    dialog.setAttribute("aria-modal","true");
    const heading=el("h2","",title);heading.id="krew-confirm-title";
    dialog.setAttribute("aria-labelledby",heading.id);
    const message=p(detail);const row=el("div","report-btns");
    const cancel=el("button","secondary","Отмена");
    const yes=el("button","danger","Подтвердить");
    let resolved=false;
    function finish(value){if(resolved)return;resolved=true;document.removeEventListener("keydown",keys);overlay.remove();resolve(value)}
    function keys(event){if(event.key==="Escape")finish(false)}
    cancel.onclick=()=>finish(false);yes.onclick=()=>finish(true);
    overlay.onclick=event=>{if(event.target===overlay)finish(false)};
    append(row,cancel,yes);append(dialog,heading,message,row);overlay.append(dialog);
    document.body.append(overlay);document.addEventListener("keydown",keys);
    cancel.focus();
  });
}

const base=()=>`/api/chats/${app.chat}`;
async function init(){
  document.querySelectorAll(".nav").forEach(btn=>btn.addEventListener("click",()=>navigate(btn.dataset.page)));
  document.getElementById("refresh-button").addEventListener("click",()=>{haptic();refresh()});
  document.getElementById("more-button").addEventListener("click",toggleMore);
  document.querySelectorAll("[data-extra-page]").forEach(btn=>btn.addEventListener("click",()=>navigate(btn.dataset.extraPage)));
  document.addEventListener("keydown",event=>{if(event.key==="Escape")closeMore()});
  document.addEventListener("click",event=>{
    if(!event.target.closest("#more-menu")&&!event.target.closest("#more-button"))closeMore();
  });
  if(preview)notify("Демо-режим: все данные вымышленные, изменения не сохраняются.");
  else if(!initData){
    notify("Открой панель из личного чата с ботом. Для просмотра дизайна добавь ?preview=1 к адресу.",true);
    content.replaceChildren(empty("Ожидается авторизация Telegram"));
    document.getElementById("chat").disabled=true;
    return;
  }
  try{
    const result=await api("/api/chats");app.chats=result.chats||[];
    const sel=document.getElementById("chat");sel.replaceChildren();
    if(!app.chats.length){
      sel.append(el("option","","Нет доступных чатов"));sel.disabled=true;
      content.replaceChildren(empty("Добавь KREW в группу, отправь /setup и проверь свои права администратора."));
      content.setAttribute("aria-busy","false");return;
    }
    for(const chat of app.chats){const option=el("option","",chat.title||String(chat.chat_id));option.value=String(chat.chat_id);sel.append(option)}
    const stored=restoredChat();
    app.chat=app.chats.some(x=>x.chat_id===stored)?stored:app.chats[0].chat_id;
    sel.value=String(app.chat);
    sel.onchange=()=>{app.chat=Number(sel.value);rememberChat(app.chat);navigate("overview")};
    await refresh();
  }catch(error){
    notify(error.message,true);
    content.replaceChildren(empty("Не удалось загрузить сообщества. Проверь подключение и попробуй ещё раз."));
    content.setAttribute("aria-busy","false");
  }
}
async function refresh(){
  if(!app.chat)return;
  if(app.renderController)app.renderController.abort();
  const controller=new AbortController();app.renderController=controller;
  const headings={
    overview:["Обзор сообщества","Всё самое важное в одном месте."],
    settings:["Настройки защиты","Быстрый контроль над правилами и безопасностью."],
    reports:["Жалобы","Решения без хаоса. Каждое действие — с историей."],
    analytics:["Аналитика","Тренды активности и динамика сообщества."],
    rulesets:["Умные фильтры","Исключения и ограничения под твоим контролем."],
    audit:["Журнал действий","История модерации и изменений настроек."],
    community:["Сообщество","Участники, достижения и внутриигровая активность."]
  };
  const names={overview:"ОБЗОР",settings:"МОДЕРАЦИЯ",reports:"ЖАЛОБЫ",analytics:"АНАЛИТИКА",rulesets:"ФИЛЬТРЫ",audit:"ЖУРНАЛ",community:"СООБЩЕСТВО"};
  document.querySelectorAll(".nav[data-page]").forEach(btn=>{
    const selected=btn.dataset.page===app.page;
    btn.classList.toggle("active",selected);
    if(selected)btn.setAttribute("aria-current","page");else btn.removeAttribute("aria-current");
  });
  const extra=["rulesets","community","audit"].includes(app.page);
  document.getElementById("more-button").classList.toggle("active",extra);
  if(extra)document.getElementById("more-button").setAttribute("aria-current","page");
  else document.getElementById("more-button").removeAttribute("aria-current");
  document.getElementById("crumb").textContent=names[app.page];
  document.getElementById("heading").textContent=headings[app.page][0];
  document.getElementById("subtitle").textContent=headings[app.page][1];
  document.getElementById("footer-state").textContent=preview?"Демо · Без сохранения":"Подключено";
  document.getElementById("refresh-button").classList.add("is-loading");
  document.getElementById("refresh-button").setAttribute("aria-busy","true");
  content.setAttribute("aria-busy","true");
  content.replaceChildren(loadingSkeleton());
  try{
    if(app.page==="overview")await renderOverview();
    else if(app.page==="settings")await renderSettings();
    else if(app.page==="reports")await renderReports();
    else if(app.page==="analytics")await renderAnalytics();
    else if(app.page==="rulesets")await renderRulesets();
    else if(app.page==="community")await renderCommunity();
    else await renderAudit();
  }catch(error){
    if(controller.signal.aborted || error.name==="AbortError")return;
    notify(error.message,true);
    content.replaceChildren(empty("Не удалось загрузить раздел. Нажми ↻, чтобы повторить."));
  }finally{
    if(app.renderController===controller){
      content.setAttribute("aria-busy","false");
      document.getElementById("refresh-button").classList.remove("is-loading");
      document.getElementById("refresh-button").setAttribute("aria-busy","false");
    }
  }
}
async function renderOverview(){
  const controller=app.renderController;const result=await api(base()+"/overview");if(!active(controller))return;
  const s=result.stats;
  const hero=el("section","hero"),copy=el("div","hero-content"),actions=el("div","hero-actions");
  const pending=Number(s.reports||0);
  append(copy,
    el("div","hero-label",pending?"◉  НУЖНО ВНИМАНИЕ":"✳  СИСТЕМА ПОД КОНТРОЛЕМ"),
    el("h2","",pending?`${fmt(pending)} ${pending===1?"жалоба ждёт":pending<5?"жалобы ждут":"жалоб ждут"} решения`:"Твой чат. Твои правила."),
    p(pending?"Открой очередь жалоб, чтобы рассмотреть обращения и сохранить порядок в сообществе.":"Все важные инструменты здесь: защита, активность и управление без лишних действий.")
  );
  const primary=el("button","primary",pending?"Проверить жалобы →":"Настроить защиту →");
  primary.onclick=()=>navigate(pending?"reports":"settings");
  const secondary=el("button","secondary","Аналитика");secondary.onclick=()=>navigate("analytics");
  append(actions,primary,secondary);append(hero,copy,actions);
  const grid=el("div","stats");
  const cards=[
    ["◈","Участников",s.members,"В учёте KREW"],
    ["◷","Сообщений",s.messages,"За всё время"],
    ["⚑","Открытых жалоб",s.reports,pending?"Ожидают решения":"Нет обращений"],
    ["▤","Модерация",s.actions,"Действий за 30 дней"]
  ];
  for(const [icon,label,value,note] of cards){
    const card=el("div","stat-card");
    append(card,append(el("div","stat-label"),el("span","stat-icon",icon),el("span","",label)),
      el("div","stat-value",fmt(value)),el("div","stat-sub",note));
    grid.append(card);
  }
  const recent=panel("Последние действия","Журнал модерации");
  if(!(result.recent||[]).length)recent.append(empty("Здесь появится история действий модерации."));
  const actionNames={warn:"Предупреждение",mute:"Ограничение",ban:"Блокировка",kick:"Исключение",captcha_timeout:"Капча не пройдена",report_warn:"Предупреждение по жалобе",pin:"Закрепление",unpin:"Открепление"};
  for(const item of result.recent||[]){
    const row=el("div","list-row"),one=el("div");
    append(one,el("div","row-title",actionNames[item.action]||String(item.action)),el("div","row-sub","Участник #"+item.target_id));
    append(row,one,el("div","action-time",new Date(item.timestamp*1000).toLocaleDateString("ru-RU")));
    recent.append(row);
  }
  const quick=panel("Под рукой","Быстрый доступ");
  quick.append(p("Настраивай защиту, просматривай отчёты и следи за активностью сообщества."));
  const wrap=el("div","report-btns");
  const settings=el("button","primary","Настройки");settings.onclick=()=>navigate("settings");
  const reports=el("button","secondary","Очередь жалоб");reports.onclick=()=>navigate("reports");
  append(wrap,settings,reports);quick.append(wrap);
  content.replaceChildren(hero,grid,append(el("div","split"),recent,quick));
}
const settingsList=[
  ["antispam","Антиспам","Защита от флуда и одинаковых сообщений"],
  ["antilinks","Фильтр ссылок","Удаляет нежелательные ссылки с учётом исключений"],
  ["captcha","Капча новичков","Проверка перед возможностью писать в чат"],
  ["antiraid","Защита от рейдов","Автоматическая проверка при массовых вступлениях"],
  ["antiforward","Запрет пересылок","Блокирует пересланные публикации"],
  ["welcome","Приветствия","Встречает новых участников"],
  ["fun","Развлечения","Доступ к играм и наградам"],
  ["levels","Уровни","Опыт за активность участников"],
  ["antimentions","Массовые упоминания","Удаляет сообщения с большим числом @упоминаний"],
  ["anticaps","CAPS-спам","Фильтр слишком длинных сообщений ЗАГЛАВНЫМИ"]
];
async function renderSettings(){
  const controller=app.renderController;const result=await api(base()+"/settings");if(!active(controller))return;const s=result.settings;
  const grid=el("div","settings-grid"),left=panel("Защита сообщества","Фильтры и правила"),right=panel("Активность участников","Социальные функции");
  settingsList.forEach(([key,title,desc],i)=>{
    const row=el("div","list-row"),name=append(el("div"),el("div","row-title",title),el("div","row-sub",desc));
    const btn=el("button","switch"+(s[key]?" on":""));btn.setAttribute("aria-label",title);btn.setAttribute("aria-pressed",String(!!s[key]));
    btn.onclick=async()=>{btn.disabled=true;try{await api(base()+"/settings","PATCH",{field:key,value:!s[key]});s[key]=!s[key];btn.classList.toggle("on",!!s[key]);btn.setAttribute("aria-pressed",String(!!s[key]));notify("Настройки сохранены" )}catch(e){notify(e.message,true)}finally{btn.disabled=false}};
    append(row,name,btn);(i<5||i>=8?left:right).append(row)
  });
  grid.append(left,right);
  const advanced=panel("Дополнительные настройки","Изменения применяются сразу");
  const warn=el("label","form-label","Лимит предупреждений (1–10)"),n=el("input","field");n.type="number";n.min="1";n.max="10";n.value=s.warn_limit;warn.append(n);
  const mentions=el("label","form-label","Лимит упоминаний (3–15)"),ml=el("input","field");ml.type="number";ml.min="3";ml.max="15";ml.value=s.mention_limit;mentions.append(ml);
  const rules=el("label","form-label","Правила чата"),area=el("textarea","field");area.rows=3;area.maxLength=1200;area.value=s.rules;rules.append(area);
  const welcome=el("label","form-label","Приветствие. {user} — имя нового участника"),w=el("textarea","field");w.rows=2;w.maxLength=500;w.value=s.welcome_text;welcome.append(w);
  const save=el("button","primary","Сохранить изменения");save.onclick=async()=>{
    const limit=Number(n.value),mentionsLimit=Number(ml.value);
    if(!Number.isInteger(limit)||limit<1||limit>10){notify("Лимит предупреждений — от 1 до 10",true);n.focus();return}
    if(!Number.isInteger(mentionsLimit)||mentionsLimit<3||mentionsLimit>15){notify("Лимит упоминаний — от 3 до 15",true);ml.focus();return}
    const changes=[["warn_limit",limit],["mention_limit",mentionsLimit],["rules",area.value],["welcome_text",w.value]]
      .filter(([field,value])=>s[field]!==value);
    if(!changes.length){notify("Все настройки уже сохранены");return}
    save.disabled=true;save.textContent="Сохраняем…";
    try{
      for(const [field,value] of changes){await api(base()+"/settings","PATCH",{field,value});s[field]=value}
      haptic();notify("Изменения сохранены");
    }catch(e){notify("Не удалось сохранить все поля: "+e.message,true)}
    finally{save.disabled=false;save.textContent="Сохранить изменения"}
  };
  advanced.append(append(el("div","settings-grid"),warn,mentions,rules,welcome),el("div",""));advanced.append(save);
  content.replaceChildren(grid,advanced)
}
async function renderReports(){
  const controller=app.renderController;const result=await api(base()+"/reports");if(!active(controller))return;const r=result.reports;
  const main=panel("Очередь обращений",`${r.length} последних открытых`);
  main.append(p("Отклонение возможно только с объяснением. Заявителю придёт сообщение в личку, если он запустил бота и разрешил уведомления."));
  if(!r.length)main.append(empty("Открытых жалоб нет"));
  for(const item of r){
    const row=el("div","report"),info=el("div");
    append(info,el("div","row-title","Жалоба #"+item.id),el("div","row-sub","От #"+item.reporter_id+" на #"+item.target_id+" · сообщение "+item.target_message_id));
    const buttons=el("div","report-btns"),reject=el("button","secondary","Отклонить"),warn=el("button","danger","Предупредить");
    const composer=el("div","reason-composer"),label=el("label","form-label","Обязательная причина отклонения (5–300 символов)"),reason=el("textarea","field");
    reason.rows=3;reason.maxLength=300;reason.placeholder="Например: Нарушение не подтвердилось, сообщение не противоречит правилам чата.";
    label.append(reason);
    const actions=el("div","report-btns"),save=el("button","primary","Подтвердить отклонение"),cancel=el("button","secondary","Отмена");
    cancel.onclick=()=>{composer.hidden=true;reason.value=""};
    reject.onclick=()=>{composer.hidden=false;reason.focus()};
    save.onclick=async()=>{
      const why=reason.value.trim();if(why.length<5||why.length>300){notify("Напиши причину от 5 до 300 символов",true);return}
      save.disabled=true;reject.disabled=true;warn.disabled=true;
      try{const res=await api(base()+`/reports/${item.id}/reject`,"POST",{reason:why});
        row.remove();await refresh();notify(res.notification_status==="sent"?"Жалоба отклонена. Заявитель уведомлён.":"Жалоба отклонена. Сообщение в личку не доставлено (см. историю).");
      }catch(e){notify(e.message,true);save.disabled=false;reject.disabled=false;warn.disabled=false}
    };
    warn.onclick=async()=>{
      if(!await confirmAction("Выдать предупреждение?","Участник #"+item.target_id+" получит предупреждение. Решение сохранится в журнале."))return;
      warn.disabled=true;reject.disabled=true;
      try{const res=await api(base()+`/reports/${item.id}/warn`,"POST",{});row.remove();await refresh();
        notify(res.warning_notification_sent===false?"Решение сохранено, но уведомление о предупреждении в чате не удалось отправить":"Предупреждение выдано. Статус ЛС: "+res.notification_status);
      }catch(e){notify(e.message,true);warn.disabled=false;reject.disabled=false}
    };
    append(actions,cancel,save);append(composer,label,actions);composer.hidden=true;
    append(buttons,el("span","tag","ОТКРЫТА"),reject,warn);append(row,info,buttons,composer);main.append(row);
  }
  const history=panel("История решений","Последние 20 рассмотренных жалоб");
  const labels={rejected:"Отклонена",warned:"Нарушение подтверждено",closed:"Закрыта"};
  if(!(result.history||[]).length)history.append(empty("Решений пока нет"));
  for(const item of result.history||[]){
    const row=el("div","decision-row"),head=el("div","decision-head");
    append(head,el("b","",`#${item.id} · ${labels[item.status]||item.status}`),el("span","tag",new Date((item.resolved_at||item.created)*1000).toLocaleDateString("ru-RU")));
    append(row,head,el("div","row-sub",item.decision_reason||"Причина отсутствует (устаревшая запись)"),
      el("div","row-sub","ЛС заявителю: "+({sent:"доставлено",failed:"не доставлено",not_started:"бот не запущен пользователем",disabled:"отключено",pending:"не отправлялось"}[item.notification_status]||"—")));
    if(item.status==="warned")row.append(el("div","row-sub","ЛС нарушителю: "+({sent:"доставлено",failed:"не доставлено",not_started:"бот не запущен пользователем",disabled:"отключено",pending:"не отправлялось"}[item.target_notification_status]||"—")));
    history.append(row);
  }
  content.replaceChildren(main,history);
}

init();


/* KREW 0.4: real Telegram-scoped analytics, rule editor, audit */
async function renderAnalytics(){
  const controller=app.renderController;const data=await api(base()+"/analytics");if(!active(controller))return;
  const days=data.timeline||[];
  const chart=panel("Динамика активности","Последние 14 дней · UTC");
  const controls=el("div","chart-controls");
  const chartArea=el("div","bars");chartArea.setAttribute("role","group");chartArea.setAttribute("aria-label","График активности");
  const summary=p("Наведите на столбец или выберите его, чтобы посмотреть значение.","chart-tooltip");
  const metrics=[
    ["messages","Сообщения"],
    ["joins","Вступления"],
    ["actions","Модерация"]
  ];
  function draw(key){
    const max=Math.max(1,...days.map(day=>Number(day[key]||0)));
    chartArea.replaceChildren();
    for(const day of days){
      const value=Math.max(0,Number(day[key]||0));
      const barWrap=el("div","bar-wrap"),bar=el("div","bar");
      const detail=`${day.day} · ${fmt(value)} ${metrics.find(row=>row[0]===key)[1].toLowerCase()}`;
      bar.style.height=(100*value/max)+"%";bar.title=detail;
      barWrap.setAttribute("role","img");barWrap.setAttribute("tabindex","0");barWrap.setAttribute("aria-label",detail);
      function update(){summary.textContent=detail}
      barWrap.onmouseenter=update;barWrap.onfocus=update;barWrap.onclick=update;
      barWrap.append(bar);chartArea.append(barWrap);
    }
    controls.querySelectorAll("button").forEach(button=>{
      const selected=button.dataset.metric===key;
      button.classList.toggle("active",selected);
      button.setAttribute("aria-pressed",String(selected));
    });
    summary.textContent=`${metrics.find(row=>row[0]===key)[1]} · всего ${fmt(days.reduce((sum,day)=>sum+Number(day[key]||0),0))} за 14 дней`;
  }
  for(const [key,label] of metrics){
    const button=el("button","chart-tab",label);button.type="button";button.dataset.metric=key;
    button.onclick=()=>{haptic();draw(key)};controls.append(button);
  }
  chart.append(controls,chartArea,append(el("div","keyline"),el("span","",days[0]?.day||"Нет данных"),el("span","",days.at(-1)?.day||"")),summary);
  draw("messages");
  const totals=days.reduce((acc,day)=>({messages:acc.messages+day.messages,joins:acc.joins+day.joins,actions:acc.actions+day.actions}),{messages:0,joins:0,actions:0});
  const report=panel("Итоги периода","Последние 14 дней");
  for(const [field,label] of [["messages","Сообщений"],["joins","Вступлений"],["actions","Действий"]]){
    const row=el("div","list-row");append(row,el("div","row-title",label),el("b","",fmt(totals[field])));report.append(row);
  }
  const leaders=panel("Лидеры сообщества","Топ по опыту");
  if(!(data.top||[]).length)leaders.append(empty("Участников пока недостаточно для рейтинга."));
  (data.top||[]).forEach((person,index)=>{
    const row=el("div","list-row");
    append(row,el("div","row-title",`${index+1}. ${person.name||"Участник"}`),el("span","muted tiny",`${fmt(person.xp)} XP`));leaders.append(row);
  });
  content.replaceChildren(append(el("div","split"),chart,report),leaders);
}
async function renderRulesets(){
  const controller=app.renderController;const data=await api(base()+"/rulesets");if(!active(controller))return;
  const holder=el("div","settings-grid");
  for(const [key,heading,description,placeholder] of [
    ["words","Запрещённые слова","Нежелательные слова и выражения в сообщениях","слово или фраза"],
    ["domains","Разрешённые домены","Исключения из фильтра ссылок (например, youtube.com)","example.com"]]){
    const c=panel(heading,"До 100 записей"),label=el("label","form-label",description),input=el("input","field");input.placeholder=placeholder;input.maxLength=55;label.append(input);
    const add=el("button","primary","Добавить");const form=append(el("div","inline-form"),label,add);c.append(form);
    const list=el("div");c.append(list);
    const draw=()=>{list.replaceChildren();if(!(data[key]||[]).length){list.append(empty("Список пуст"));return}
      data[key].forEach(value=>{const row=el("div","list-row"),del=el("button","secondary","Удалить");
        del.onclick=async()=>{del.disabled=true;try{const res=await api(base()+"/"+key,"POST",{action:"remove",value});Object.assign(data,res);draw();notify("Удалено")}catch(e){notify(e.message,true);del.disabled=false}};
        append(row,el("span","row-title",value),del);list.append(row)})};
    add.onclick=async()=>{add.disabled=true;try{const res=await api(base()+"/"+key,"POST",{action:"add",value:input.value.trim()});Object.assign(data,res);input.value="";draw();notify("Добавлено")}catch(e){notify(e.message,true)}finally{add.disabled=false}};
    draw();holder.append(c)
  }
  content.replaceChildren(holder);
}
async function renderAudit(){
  const controller=app.renderController;const data=await api(base()+"/audit");if(!active(controller))return;const list=panel("Изменения настроек","История за 30 дней"),actions=panel("Модерация","Последние действия");
  if(!data.audit.length)list.append(empty("Изменений пока нет"));
  for(const a of data.audit){const row=el("div","list-row"),label=el("div");
    append(label,el("div","row-title",String(a.field)),el("div","row-sub","Модератор #"+a.actor_id+" · "+String(a.old_value)+" → "+String(a.new_value)));
    append(row,label,el("span","action-time",new Date(a.created*1000).toLocaleDateString("ru-RU")));list.append(row)}
  if(!data.recent.length)actions.append(empty("Пока нет записей"));
  for(const a of data.recent){const row=el("div","list-row"),label=el("div");
    append(label,el("div","row-title",String(a.action)),el("div","row-sub","Участник #"+a.target_id));
    append(row,label,el("span","action-time",new Date(a.timestamp*1000).toLocaleDateString("ru-RU")));actions.append(row)}
  content.replaceChildren(append(el("div","split"),list,actions));
}

/* KREW 0.6: Community dashboard. Server data only in authenticated mode. */
async function renderCommunity(){
  const controller=app.renderController;const data=(await api(base()+"/community")).community;if(!active(controller))return;
  const grid=el("div","stats");
  for(const [icon,label,value,note] of [
    ["◉","Активны сегодня",data.active_today,"Участники с прогрессом задания"],
    ["✦","Задания выполнены",data.claimed_today,"Награды за сегодня"],
    ["♡","Благодарностей",data.thanks_today,"Сегодня в чате"],
    ["♢","Награда задания",data.mission_reward+" 🪙","За 5 сообщений с паузами"]]){
    const c=el("div","stat-card");append(c,append(el("div","stat-label"),el("span","stat-icon",icon),el("span","",label)),el("div","stat-value",value),el("div","stat-sub",note));grid.append(c);
  }
  const left=panel("Рейтинг добрых дел","По благодарностям участников");
  if(!data.top_reputation.length)left.append(empty("Ещё никто не получил благодарностей"));
  data.top_reputation.forEach((u,i)=>{const r=el("div","list-row");append(r,el("div","row-title",`${i+1}. ${u.name || "Участник #"+u.user_id}`),el("span","muted tiny",`${u.reputation} 💜`));left.append(r)});
  const right=panel("Ежедневное задание","Честная игровая прогрессия");
  right.append(p("Участники пишут 5 сообщений с интервалом минимум 60 секунд. За каждое засчитанное сообщение начисляется XP, а после выполнения можно получить 35 монет."));
  right.append(p("Команды: /mission — прогресс, /claim — получить награду, /thanks — поблагодарить другого участника (ответом)."));
  right.append(p("Сброс и выдача новых попыток происходят в 00:00 UTC. Все награды исключительно игровые."));
  content.replaceChildren(grid,append(el("div","split"),left,right));
}

// KREW Control Center 2.0: responsive navigation, abort-safe updates, interactive analytics.
