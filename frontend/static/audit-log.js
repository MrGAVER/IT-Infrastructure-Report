// audit-log.js — раздел «Аудит»: фильтр по разделу/дате, экспорт в Excel, рендер журнала
// (auditQueryParams/setAuditFilter/resetAuditFilters/exportAuditLog/renderAuditLog).
//
// Седьмой шаг разбиения app.js (см. docs/frontend-modularization.md, вариант C). Самодостаточный
// экран: единственная внешняя зависимость — общие утилиты get/api/esc/notify/withBusyButton из
// core.js и openResource()/showDashboard() из app.js (диспетчеризация маршрута верхнего уровня).
// auditFilters — var, а не let, по той же причине, что и раньше (см. историю коммита 2219cd5):
// let-биндинг верхнего уровня не становится свойством window, тесты не смогли бы прочитать/
// подменить состояние фильтра через win.auditFilters.

// var, не let: остальное состояние маршрутизации в этом файле (resource, schema, rows) — тоже
// на уровне window через неявные глобальные присваивания, а let-биндинг верхнего уровня НЕ
// становится свойством window (виден только изнутри самого app.js) — тесты и другие модули не
// смогли бы прочитать/подменить его через win.auditFilters.
var auditFilters={entityType:'',dateFrom:'',dateTo:''};
function auditQueryParams(){
 const p=new URLSearchParams();
 if(auditFilters.entityType) p.set('entity_type',auditFilters.entityType);
 if(auditFilters.dateFrom) p.set('date_from',auditFilters.dateFrom);
 if(auditFilters.dateTo) p.set('date_to',auditFilters.dateTo);
 return p;
}
function setAuditFilter(key,value){auditFilters={...auditFilters,[key]:value};renderAuditLog();}
function resetAuditFilters(){auditFilters={entityType:'',dateFrom:'',dateTo:''};renderAuditLog();}
async function exportAuditLog(btn){
 await withBusyButton(btn,async()=>{
   try{
     const qs=auditQueryParams().toString();
     const x=await get(api+'/reports/audit-log'+(qs?`?${qs}`:''),{method:'POST'});
     window.location=x.download_url;
   }catch(e){notifyError(e)}
 });
}
async function renderAuditLog(){
 const qs=auditQueryParams();qs.set('limit','300');
 const [logData,resourceList]=await Promise.all([
   get(api+`/resources/audit-log?${qs.toString()}`),
   get(api+'/resources'),
 ]);
 const resourceNames=Object.fromEntries(resourceList.map(r=>[r.key,r.name]));
 const rows=logData.items; // сервер уже сортирует по created_at desc — см. services/crud.list_resource
 // Резолвим человекочитаемые подписи записей пакетно по типу сущности (один запрос на тип,
 // а не один запрос на каждую строку журнала). SYNC-записи интерфейсов ссылаются на устройство
 // (entity_id — это id устройства, а не интерфейса), поэтому резолвим их по 'devices'.
 const lookupType=r=>(r.entity_type==='interfaces'&&r.action==='SYNC')?'devices':r.entity_type;
 const byType={};
 for(const r of rows){const t=lookupType(r);(byType[t]=byType[t]||[]).push(r);}
 const labelCache={};
 for(const type of Object.keys(byType)){
   try{const all=(await get(api+`/resources/${type}?limit=1000`)).items;labelCache[type]=Object.fromEntries(all.map(o=>[o.id,lookupLabel(type,o)]));}
   catch(_){labelCache[type]={};}
 }
 const actionLabels={CREATE:'Создание',UPDATE:'Изменение',DELETE:'Удаление',SYNC:'Синхронизация'};
 const filterActive=auditFilters.entityType||auditFilters.dateFrom||auditFilters.dateTo;
 const sectionOptions=`<option value="">Все разделы</option>`+resourceList.map(r=>`<option value="${esc(r.key)}"${auditFilters.entityType===r.key?' selected':''}>${esc(r.name)}</option>`).join('');
 content.innerHTML=`<div class="top"><div><h2>Аудит</h2><div class="muted">${filterActive?`Найдено по фильтру: ${rows.length}`:`Последние ${rows.length} действий`}</div></div><div><button class="btn gray" onclick="exportAuditLog(this)">Экспорт в Excel</button> <button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel"><div class="bulk-edit-bar" style="margin-bottom:14px"><label class="field"><span class="if-select-label">Раздел</span><select onchange="setAuditFilter('entityType',this.value)">${sectionOptions}</select></label><label class="field"><span class="if-select-label">С</span><input type="date" value="${esc(auditFilters.dateFrom)}" onchange="setAuditFilter('dateFrom',this.value)"></label><label class="field"><span class="if-select-label">По</span><input type="date" value="${esc(auditFilters.dateTo)}" onchange="setAuditFilter('dateTo',this.value)"></label>${filterActive?'<button class="btn gray" onclick="resetAuditFilters()">Сбросить фильтр</button>':''}</div><div class="tablewrap"><table><thead><tr><th>Дата и время</th><th>Раздел</th><th>Запись</th><th>Действие</th><th>Подробности</th></tr></thead><tbody>${rows.map(r=>{
   const t=lookupType(r);
   const label=labelCache[t]?.[r.entity_id];
   const entityCell=label?esc(label):`<span class="muted">запись удалена (${esc((r.entity_id||'').slice(0,8))}…)</span>`;
   const when=r.created_at?new Date(r.created_at).toLocaleString('ru-RU'):'';
   return `<tr><td>${esc(when)}</td><td>${esc(resourceNames[r.entity_type]||r.entity_type)}</td><td>${entityCell}</td><td>${esc(actionLabels[r.action]||r.action)}</td><td>${esc(r.details||'')}</td></tr>`;
 }).join('')||`<tr><td colspan="5" class="muted">${filterActive?'Ничего не найдено по заданному фильтру':'Записей нет'}</td></tr>`}</tbody></table></div></div>`;
}
