"use strict";
/* KREW Control Center. No third-party frontend dependencies. */
const tg = window.Telegram && window.Telegram.WebApp;
if (tg) { try {tg.ready();tg.expand()} catch (_) {} }
const preview = new URLSearchParams(location.search).has("preview");
const initData = tg ? (tg.initData || "") : "";
const app = {
  chat: null, page:"overview", chats:[],
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
function notify(message,error=false){const n=document.getElementById("notice");n.hidden=false;n.className="notice"+(error?" error":"");n.textContent=message;}
function silence(){document.getElementById("notice").hidden=true}
function panel(title,sub){const n=el("div","panel"),head=el("div","panel-head");append(head,el("h2","",title),sub?el("span","muted tiny",sub):null);n.append(head);return n}
function empty(msg){return el("div","empty",msg)}
async function api(path,method="GET",payload){
  if(preview){return fake(path,method,payload)}
  if(!initData)throw Error("Откройте приложение через меню бота в Telegram. В браузере доступен только демонстрационный режим ?preview=1.");
  const response=await fetch(path,{method,headers:{"Authorization":"tma "+initData,...(payload?{"Content-Type":"application/json"}:{})},body:payload?JSON.stringify(payload):undefined,cache:"no-store"});
  const result=await response.json();if(!response.ok)throw Error(result.error||"Ошибка сервера");return result;
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
const base=()=>`/api/chats/${app.chat}`;
async function init(){
  if(preview)notify("ДЕМО-РЕЖИМ — вымышленные данные. Изменения не сохраняются.");
  else if(!initData){notify("Открой панель из личного чата с ботом. Для просмотра дизайна: добавь ?preview=1 к адресу.",true);content.replaceChildren(empty("Ожидается авторизация Telegram"));document.getElementById("chat").disabled=true;return;}
  try{
    const result=await api("/api/chats");app.chats=result.chats;
    const sel=document.getElementById("chat");sel.replaceChildren();
    if(!app.chats.length){sel.append(el("option","","Нет доступных чатов"));sel.disabled=true;content.replaceChildren(empty("Добавь бота в группу, отправь /setup и проверь, что ты её администратор."));return;}
    for(const c of app.chats){const o=el("option","",c.title||String(c.chat_id));o.value=String(c.chat_id);sel.append(o)}
    app.chat=app.chats[0].chat_id;sel.value=String(app.chat);sel.onchange=()=>{app.chat=Number(sel.value);refresh()};
    document.querySelectorAll(".nav").forEach(btn=>btn.addEventListener("click",()=>{app.page=btn.dataset.page;refresh()}));
    await refresh();
  }catch(e){notify(e.message,true);content.replaceChildren(empty("Не удалось загрузить сообщества"));}
}
async function refresh(){
  if(!app.chat)return;
  const titles={overview:["Обзор сообщества","Ваше пространство для управления и аналитики."],settings:["Настройки модерации","Полный контроль над безопасностью и атмосферой чата."],reports:["Очередь жалоб","Рассматривайте обращения участников и отслеживайте порядок."],analytics:["Аналитика активности","История сообщений, вступлений и действий модерации."],rulesets:["Умные фильтры","Управляйте запрещёнными словами и разрешёнными доменами."],audit:["Журнал изменений","Прозрачная история действий администрации."],community:["Активность сообщества","Задания, благодарности и живое сообщество."]};
  document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.page===app.page));
  document.getElementById("crumb").textContent=app.page.toUpperCase();
  document.getElementById("heading").textContent=titles[app.page][0];
  document.getElementById("subtitle").textContent=titles[app.page][1];
  document.getElementById("footer-state").textContent=preview?"Демо":"Подключено";
  content.replaceChildren(el("div","loading","Загрузка..."));
  try{if(app.page==="overview")await renderOverview();else if(app.page==="settings")await renderSettings();else if(app.page==="reports")await renderReports();else if(app.page==="analytics")await renderAnalytics();else if(app.page==="rulesets")await renderRulesets();else if(app.page==="community")await renderCommunity();else await renderAudit();}
  catch(e){notify(e.message,true);content.replaceChildren(empty("Ошибка загрузки. Попробуйте открыть раздел ещё раз."))}
}
async function renderOverview(){
  const result=await api(base()+"/overview");const s=result.stats;
  const grid=el("div","stats");
  const cards=[["◈","Участников",s.members,"Учтённых пользователей"],["◷","Сообщений",s.messages,"За всё время"],["⚑","Жалоб открыто",s.reports,"Требуют внимания"],["▤","Действий",s.actions,"В журнале за 30 дней"]];
  for(const [ico,label,value,note] of cards){const c=el("div","stat-card");append(c,append(el("div","stat-label"),el("span","stat-icon",ico),el("span","",label)),el("div","stat-value",fmt(value)),el("div","stat-sub",note));grid.append(c)}
  const left=panel("Последние действия","История модерации");
  if(!result.recent.length)left.append(empty("В журнале пока ничего нет"));
  for(const item of result.recent){const row=el("div","list-row"),one=el("div");append(one,el("div","row-title",String(item.action)),el("div","row-sub","Участник #"+item.target_id));append(row,one,el("div","action-time",new Date(item.timestamp*1000).toLocaleDateString("ru-RU")));left.append(row)}
  const right=panel("Быстрые действия","Управление");
  right.append(p("Управляйте фильтрами и жалобами прямо из Telegram, без десятков команд."));
  const b=el("button","primary","Открыть настройки →");b.onclick=()=>{app.page="settings";refresh()};right.append(b);
  const second=el("button","secondary","Посмотреть жалобы");second.style.margin="9px 0 0 8px";second.onclick=()=>{app.page="reports";refresh()};right.append(second);
  content.replaceChildren(grid,append(el("div","split"),left,right));
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
  const result=await api(base()+"/settings"),s=result.settings;
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
  const save=el("button","primary","Сохранить изменения");save.onclick=async()=>{save.disabled=true;try{
    const changes=[["warn_limit",Number(n.value)],["mention_limit",Number(ml.value)],["rules",area.value],["welcome_text",w.value]];
    for(const [field,value] of changes)if(s[field]!==value){await api(base()+"/settings","PATCH",{field,value});s[field]=value}
    notify("Изменения сохранены");
  }catch(e){notify(e.message,true)}finally{save.disabled=false}};
  advanced.append(append(el("div","settings-grid"),warn,mentions,rules,welcome),el("div",""));advanced.append(save);
  content.replaceChildren(grid,advanced)
}
async function renderReports(){
  const result=await api(base()+"/reports"),r=result.reports;
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
      if(!window.confirm("Подтвердить нарушение и выдать предупреждение участнику #"+item.target_id+"?"))return;
      warn.disabled=true;reject.disabled=true;
      try{const res=await api(base()+`/reports/${item.id}/warn`,"POST",{});row.remove();await refresh();
        notify(res.warning_notification_sent===false?"Решение сохранено, но уведомление о предупреждении в чате не удалось отправить":"Предупреждение выдано. Статус ЛС: "+res.notification_status);
      }catch(e){notify(e.message,true);warn.disabled=false;reject.disabled=false}
    };
    append(actions,cancel,save);append(composer,label,actions);composer.hidden=true;
    append(buttons,el("span","tag","OPEN"),reject,warn);append(row,info,buttons,composer);main.append(row);
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
  const data=await api(base()+"/analytics");const days=data.timeline;
  const c=panel("Активность по дням","14 дней · UTC"),bars=el("div","bars");
  const max=Math.max(1,...days.map(x=>x.messages));
  days.forEach(row=>{const wrap=el("div","bar-wrap"),bar=el("div","bar");bar.style.height=(100*row.messages/max)+"%";bar.title=row.day+" · "+row.messages+" сообщений";wrap.append(bar);bars.append(wrap)});
  append(c,bars,append(el("div","keyline"),el("span","",days[0]?.day||""),el("span","",days.at(-1)?.day||"")));
  const summary=panel("Итоги периода","Счётчики с версии 0.3");
  const totals=days.reduce((acc,d)=>({messages:acc.messages+d.messages,joins:acc.joins+d.joins,actions:acc.actions+d.actions}),{messages:0,joins:0,actions:0});
  for(const [key,name] of [["messages","Сообщения"],["joins","Новые участники"],["actions","Модерация"]]){
    const r=el("div","list-row");append(r,el("div","row-title",name),el("b","",fmt(totals[key])));summary.append(r)}
  const leaders=panel("Лидеры сообщества","По опыту");
  if(!data.top.length)leaders.append(empty("Недостаточно данных"));
  data.top.forEach((u,i)=>{const row=el("div","list-row");append(row,el("div","row-title",`${i+1}. ${u.name||"Участник"}`),el("span","muted tiny",`${fmt(u.xp)} XP`));leaders.append(row)});
  content.replaceChildren(append(el("div","split"),c,summary),leaders);
}
async function renderRulesets(){
  const data=await api(base()+"/rulesets");
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
  const data=await api(base()+"/audit"),list=panel("Изменения настроек","История за 30 дней"),actions=panel("Модерация","Последние действия");
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
  const data=(await api(base()+"/community")).community;
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
