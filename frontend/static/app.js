// app.js — маршрутизация, дашборд, универсальный список/форма ресурсов, формы ИС/устройства/
// подключения, интерфейсы и VLAN устройства, быстрое добавление в справочники, импорт CSV.
//
// Базовые утилиты без зависимостей вынесены в core.js, редакторы вложенных списков ВМ/устройства
// (VM IP/порты/ПО, открытые порты устройства) — в vm-editors.js. Оба подключаются раньше этого
// файла (см. index.html), поэтому их функции/константы доступны здесь напрямую.

let globalSearchResults=[];
async function globalSearch(q){
 q=(q||'').trim();
 if(!q)return;
 const enc=encodeURIComponent(q);
 const safeList=async(url)=>{try{return (await get(url)).items;}catch(_){return [];}};
 const [devices,isys,vms,interfaces,ifaceIps,vmIps]=await Promise.all([
   safeList(api+`/resources/devices?q=${enc}&limit=15`),
   safeList(api+`/resources/information-systems?q=${enc}&limit=15`),
   safeList(api+`/resources/vms?q=${enc}&limit=15`),
   safeList(api+`/resources/interfaces?q=${enc}&limit=15`),
   safeList(api+`/resources/interface-ips?q=${enc}&limit=15`),
   safeList(api+`/resources/vm-ips?q=${enc}&limit=15`),
 ]);
 const results=[];
 for(const d of devices)results.push({section:'Физические устройства',title:lookupLabel('devices',d),open:async()=>{await openResource('devices');await openForm(d.id);}});
 for(const s of isys)results.push({section:'Информационные системы',title:s.name||s.id,open:async()=>{await openResource('information-systems');await openForm(s.id);}});
 for(const v of vms)results.push({section:'Виртуальные машины',title:v.name||v.id,open:async()=>{await openResource('vms');await openForm(v.id);}});
 for(const i of interfaces)results.push({section:'Интерфейсы',title:lookupLabel('interfaces',i),open:async()=>{await openResource('interfaces');await openForm(i.id);}});
 for(const ip of ifaceIps){
   try{
     const iface=await get(api+`/resources/interfaces/${ip.interface_id}`);
     const dev=await get(api+`/resources/devices/${iface.physical_device_id}`);
     results.push({section:'IP интерфейсов',title:`${ip.ip_address} — ${lookupLabel('devices',dev)} / ${iface.name}`,open:async()=>{await openResource('devices');await openForm(dev.id);}});
   }catch(_){}
 }
 for(const ip of vmIps){
   try{
     const vm=await get(api+`/resources/vms/${ip.virtual_machine_id}`);
     results.push({section:'IP виртуальных машин',title:`${ip.ip_address} — ${vm.name}`,open:async()=>{await openResource('vms');await openForm(vm.id);}});
   }catch(_){}
 }
 globalSearchResults=results;
 renderGlobalSearchResults(q,results);
}
function renderGlobalSearchResults(q,results){
 content.innerHTML=`<div class="top"><div><h2>Результаты поиска: «${esc(q)}»</h2><div class="muted">${results.length} совпадений</div></div><div><button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel">${
   results.length?results.map((r,i)=>`<div class="nested-row" style="cursor:pointer" onclick="globalSearchResults[${i}].open()"><b>${esc(r.title)}</b><span class="muted">${esc(r.section)}</span><span class="muted">Открыть →</span></div>`).join(''):'<div class="muted" style="padding:20px">Ничего не найдено</div>'
 }</div>`;
}
async function showDashboard(){
 const d=await get(api+'/dashboard');
 const cards=[['information_systems','ИС','information-systems'],['physical_devices','Физические устройства','devices'],['virtual_machines','VM','vms'],['containers','Контейнеры','containers'],['connections','Подключения','connections'],['vlan','VLAN','vlans'],['software','ПО','software-assets']];
 content.innerHTML=`<div class="top"><h2>Dashboard</h2><div class="actions"><button class="btn gray" onclick="generateTestData()">Заполнить тестовыми данными</button><button class="btn gray" onclick="openResource('audit-log')">Аудит</button><button class="btn" onclick="generateReport()">Сформировать Excel</button></div></div><div class="cards">${cards.map(x=>`<button class="card" style="text-align:left;cursor:pointer" onclick="openResource('${x[2]}')"><span>${x[1]}</span><b>${d[x[0]]||0}</b><span class="muted">Открыть →</span></button>`).join('')}</div>`;
}
async function openResource(r){resource=r;if(r==='vlans'){await renderVlanDashboard();return;}if(r==='audit-log'){await renderAuditLog();return;}schema=await get(api+`/resources/${r}/schema`);await renderList()}
async function renderAuditLog(){
 const [logData,resourceList]=await Promise.all([
   get(api+'/resources/audit-log?limit=300'),
   get(api+'/resources'),
 ]);
 const resourceNames=Object.fromEntries(resourceList.map(r=>[r.key,r.name]));
 const rows=[...logData.items].sort((a,b)=>new Date(b.created_at)-new Date(a.created_at));
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
 content.innerHTML=`<div class="top"><div><h2>Аудит</h2><div class="muted">Последние ${rows.length} действий</div></div><div><button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel"><div class="tablewrap"><table><thead><tr><th>Дата и время</th><th>Раздел</th><th>Запись</th><th>Действие</th><th>Подробности</th></tr></thead><tbody>${rows.map(r=>{
   const t=lookupType(r);
   const label=labelCache[t]?.[r.entity_id];
   const entityCell=label?esc(label):`<span class="muted">запись удалена (${esc((r.entity_id||'').slice(0,8))}…)</span>`;
   const when=r.created_at?new Date(r.created_at).toLocaleString('ru-RU'):'';
   return `<tr><td>${esc(when)}</td><td>${esc(resourceNames[r.entity_type]||r.entity_type)}</td><td>${entityCell}</td><td>${esc(actionLabels[r.action]||r.action)}</td><td>${esc(r.details||'')}</td></tr>`;
 }).join('')||'<tr><td colspan="5" class="muted">Записей нет</td></tr>'}</tbody></table></div></div>`;
}
async function generateTestData(){if(!confirm('Добавить демонстрационные тестовые данные? Существующие данные не будут удалены.'))return;try{const r=await get(api+'/seed/test',{method:'POST'});notify(r.message+`\nИдентификатор набора: ${r.tag}`,'success');await showDashboard();}catch(e){notifyError(e)}}
async function renderVlanDashboard(){
 const data=await get(api+'/vlan-dashboard');
 document.getElementById('content').innerHTML=`<div class="top"><div><h2>VLAN</h2><div class="muted">Одинаковый VLAN ID может иметь разные названия и описания на разных устройствах</div></div><div><button class="btn" onclick="openForm()">+ VLAN</button><button class="btn gray" onclick="openResource('vlan-domains')">Домены VLAN</button><button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel"><div class="tablewrap"><table><thead><tr><th>VLAN ID</th><th>Название / описание</th><th>Домен</th><th>Устройства</th><th>IP / управление</th><th>Действия</th></tr></thead><tbody>${data.items.map(g=>g.definitions.map((v,j)=>`<tr>${j===0?`<td rowspan="${g.definitions.length}"><b>${esc(g.vlan_id)}</b></td>`:''}<td><b>${esc(v.name)}</b><br><span class="muted">${esc(v.description||'')}</span></td><td>${esc(v.domain_name)}</td><td>${esc(v.devices.map(d=>d.device_name).join(', ')||'—')}</td><td>${esc(v.devices.map(d=>d.ip_address?d.ip_address+(d.is_management?' (управление)':''):'не назначен').join(', ')||'—')}</td><td><button class="btn gray" onclick="openForm('${v.id}')">Изменить</button> <button class="btn red" onclick="removeItem('${v.id}')">Удалить</button></td></tr>`).join('')).join('')}</tbody></table></div></div>`;
}
async function renderList(q=''){
 const d=await get(api+`/resources/${resource}?limit=200&q=${encodeURIComponent(q)}`);rows=d.items;
 let cols=schema.columns.filter(c=>!['created_at','updated_at'].includes(c.name));
 if(resource==='devices') cols=[...cols.filter(c=>!['management_port','management_ip','physical_port_count'].includes(c.name)),{name:'management_interface',type:'TEXT',nullable:true},{name:'management_ips',type:'TEXT',nullable:true}];
 if(resource==='interfaces') cols=[...cols,{name:'ip_addresses',type:'TEXT',nullable:true}];
 if(resource==='connections') cols=[...cols.filter(c=>!['source_interface_id','destination_interface_id','connection_type_id'].includes(c.name)),{name:'source_device_name',type:'TEXT',nullable:true},{name:'source_interface_name',type:'TEXT',nullable:true},{name:'destination_device_name',type:'TEXT',nullable:true},{name:'destination_interface_name',type:'TEXT',nullable:true},{name:'connection_type_name',type:'TEXT',nullable:true}];
 if(resource==='information-systems') cols=[...cols.filter(c=>!['type','status','number','support_organization_id','support_method_id'].includes(c.name)),{name:'departments_summary',type:'TEXT',nullable:true},{name:'support_organization_name',type:'TEXT',nullable:true},{name:'support_method_name',type:'TEXT',nullable:true},{name:'protocols_summary',type:'TEXT',nullable:true},{name:'ip_addresses_summary',type:'TEXT',nullable:true},{name:'physical_devices_summary',type:'TEXT',nullable:true},{name:'vms_summary',type:'TEXT',nullable:true},{name:'containers_summary',type:'TEXT',nullable:true}];
 const lookups={};
 for(const c of cols.filter(x=>x.foreign_key)){
   const target=c.foreign_key.split('.')[0],rr=resourceMap[target];
   if(rr)try{lookups[c.name]=Object.fromEntries((await get(api+`/resources/${rr}?limit=1000`)).items.map(o=>[o.id,lookupLabel(rr,o)]));}catch(_){ }
 }
 listCols=cols;listLookups=lookups;listSortColumn=null;listSortDirection=1;
 content.innerHTML=`<div class="top"><div><h2>${schema.name}</h2><div class="muted">${d.total} записей</div></div><div><button class="btn" onclick="openForm()">+ Добавить</button> ${resource==='devices'?'<button class="btn gray" onclick="openCsvImport()">Импорт из CSV</button> ':''}<button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel"><div class="toolbar"><input id="search" placeholder="Поиск..." onkeydown="if(event.key==='Enter')renderList(this.value)"><button class="btn gray" onclick="renderList(document.getElementById('search').value)">Найти</button></div><div class="tablewrap"><table><thead><tr id="list-head"></tr></thead><tbody id="list-body"></tbody></table></div></div>`;
 renderTable();
}
function listCell(row,c){if(c.foreign_key)return listLookups[c.name]?.[row[c.name]]||'';return formatValue(row[c.name]);}
function renderTable(){
 const head=document.getElementById('list-head'),body=document.getElementById('list-body');
 if(!head||!body)return;
 head.innerHTML=listCols.map(c=>{
   const active=listSortColumn===c.name;
   const arrow=active?(listSortDirection===1?' ▲':' ▼'):'';
   return `<th class="sortable-th" onclick="sortListBy('${c.name}')">${esc(labels[c.name]||c.name)}${arrow}</th>`;
 }).join('')+'<th>Действия</th>';
 body.innerHTML=rows.map(x=>`<tr>${listCols.map(c=>`<td>${esc(listCell(x,c))}</td>`).join('')}<td><button class="btn gray" onclick="openForm('${x.id}')">Изменить</button> <button class="btn red" onclick="removeItem('${x.id}')">Удалить</button></td></tr>`).join('');
}
function sortListBy(colName){
 if(listSortColumn===colName)listSortDirection=-listSortDirection;
 else{listSortColumn=colName;listSortDirection=1;}
 const col=listCols.find(c=>c.name===colName);
 rows=[...rows].sort((a,b)=>{
   const av=col?.foreign_key?listCell(a,col):a[colName];
   const bv=col?.foreign_key?listCell(b,col):b[colName];
   if(av==null&&bv==null)return 0;
   if(av==null)return 1;
   if(bv==null)return -1;
   if(typeof av==='number'&&typeof bv==='number')return listSortDirection*(av-bv);
   return listSortDirection*String(av).localeCompare(String(bv),'ru');
 });
 renderTable();
}
async function openInformationSystemForm(id=''){
 const [item, details, supportOrgs, supportMethods, placementAssetsCatalog, cryptoMeans, deps, allDevices, deviceTypes, allVms, containers, protocolCatalogs] = await Promise.all([
   id?get(api+`/resources/information-systems/${id}`):Promise.resolve({}),
   id?get(api+`/resources/information-systems/${id}/details`):Promise.resolve({departments:[],ips:[],protocols:[],devices:[],vms:[],containers:[],sources:[]}),
   get(api+'/resources/support-organizations?limit=1000').then(r=>r.items),
   get(api+'/resources/support-methods?limit=1000').then(r=>r.items),
   get(api+'/resources/placement-assets?limit=1000').then(r=>r.items),
   get(api+'/resources/crypto-protection-means?limit=1000').then(r=>r.items),
   get(api+'/resources/departments?limit=1000').then(r=>r.items),
   get(api+'/resources/devices?limit=1000').then(r=>r.items),
   get(api+'/resources/device-types?limit=1000').then(r=>r.items),
   get(api+'/resources/vms?limit=1000').then(r=>r.items),
   get(api+'/resources/containers?limit=1000').then(r=>r.items),
   get(api+'/resources/protocol-port-catalog?limit=1000').then(r=>r.items),
 ]);
 const devices=allDevices.filter(d=>{const t=deviceTypes.find(x=>x.id===d.device_type_id);const n=(t?.name||'').toLowerCase();return n.includes('сервер')||n.includes('система хранения')||n.includes('storage')});
 let sources=details.sources||[];
 if(!sources.length){
   sources=(details.devices||[]).map(x=>({source_type:'device',physical_device_id:x.physical_device_id,virtual_machine_id:null,container_id:null,ip_address:'',purpose:'',role:x.role||'',external_interaction:false}));
   sources.push(...(details.vms||[]).map(x=>({source_type:'vm',physical_device_id:null,virtual_machine_id:x.virtual_machine_id,container_id:null,ip_address:'',purpose:'',role:x.role||'',external_interaction:false})));
   sources.push(...(details.containers||[]).map(x=>({source_type:'container',physical_device_id:null,virtual_machine_id:null,container_id:x.container_id,ip_address:'',purpose:'',role:x.role||'',external_interaction:false})));
   const used=new Set(sources.map(x=>`${x.source_type}:${x.physical_device_id||x.virtual_machine_id||x.container_id||''}`));
   for(const ip of (details.ips||[])){
     const key=ip.virtual_machine_id?`vm:${ip.virtual_machine_id}`:ip.physical_device_id?`device:${ip.physical_device_id}`:`manual:${ip.ip_address}`;
     const existing=sources.find(x=>`${x.source_type}:${x.physical_device_id||x.virtual_machine_id||x.container_id||''}`===key);
     if(existing){existing.ip_address=existing.ip_address?`${existing.ip_address}, ${ip.ip_address}`:ip.ip_address;existing.purpose=ip.purpose||existing.purpose;existing.external_interaction=!!ip.external_interaction;}
     else sources.push({source_type:'manual',physical_device_id:null,virtual_machine_id:null,container_id:null,ip_address:ip.ip_address||'',purpose:ip.purpose||'',role:'',external_interaction:!!ip.external_interaction});
   }
 }
 window.isEditor={item,details:{...details,sources,protocols:details.protocols||[],departments:details.departments||[],placement_assets:details.placement_assets||[]},supportOrgs,supportMethods,cryptoMeans,deps,devices,vms:allVms,containers,protocolCatalogs,placementAssetsCatalog};
 document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+'Информационная система';
 document.getElementById('formGrid').innerHTML=`
 <div class="field full"><span>Наименование информационной системы *</span><input id="is-name" required value="${esc(item.name||'')}"></div>
 <div class="field full"><span>Общее описание</span><textarea id="is-description">${esc(item.description||'')}</textarea></div>
 <div class="field full"><span>Назначение использования</span><textarea id="is-purpose">${esc(item.purpose||'')}</textarea></div>
 <div class="field full"><span>Локализация</span><textarea id="is-localization">${esc(item.localization||'')}</textarea></div>
 <div class="field full"><span>Работники, группы работников или подразделения использующие ИС</span><div id="is-departments" class="nested-list"></div><button type="button" class="btn gray" onclick="addISDepartment()">+ Подразделение</button></div>
 <div class="field full"><span>Организация, информационная система которой осуществляет взаимодействие и/или обеспечивает техническую поддержку</span><div class="lookup-row"><select id="is-support-org"><option value="">— не выбрано —</option>${supportOrgs.map(o=>`<option value="${esc(o.id)}" ${o.id===item.support_organization_id?'selected':''}>${esc(lookupLabel('support-organizations',o))}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('support-organizations','is-support-org')">＋</button></div></div>
 <div class="field full"><span>Способ оказания технической поддержки</span><div class="lookup-row"><select id="is-support-method"><option value="">— не выбрано —</option>${supportMethods.map(o=>`<option value="${esc(o.id)}" ${o.id===item.support_method_id?'selected':''}>${esc(o.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('support-methods','is-support-method')">＋</button></div></div>
 <div class="field full"><span>Описание процесса функционирования ИС, особенности организации направления потоков</span><textarea id="is-process">${esc(item.process_description||'')}</textarea></div>
 <div class="field full"><span>Протоколы передачи данных</span><div id="is-protocols" class="nested-list"></div><button type="button" class="btn gray" onclick="addISProtocol()">+ Протокол</button></div>
 <div class="field full"><span>Размещение, IP-адреса и источники данных ИС</span><div class="muted">В одной строке можно выбрать источник из базы или ввести IP вручную. Для физического сервера/ВМ/контейнера IP подставляются автоматически.</div><div id="is-sources" class="nested-list"></div><button type="button" class="btn gray" onclick="addISSource()">+ Источник / IP</button>
 <div class="muted" style="margin-top:10px">Оборудование, ПО, интерфейс на которых размещается ИС (для случаев, не описываемых конкретным сервером/ВМ/контейнером — например прикладное ПО или интерфейс внешнего взаимодействия)</div>
 <div id="is-placement-assets" class="nested-list"></div><button type="button" class="btn gray" onclick="addISPlacementAsset()">+ Оборудование / ПО / интерфейс</button></div>
 <div class="field"><span>СКЗИ</span><select id="is-crypto"><option value="false" ${!item.crypto_protection_enabled?'selected':''}>Нет</option><option value="true" ${item.crypto_protection_enabled?'selected':''}>Да</option></select></div>
 <div class="field"><span>Описание СКЗИ</span><div class="lookup-row"><select id="is-crypto-description"><option value="">— не выбрано —</option>${cryptoMeans.map(o=>`<option value="${esc(o.id)}" ${o.id===item.crypto_protection_description_id?'selected':''}>${esc(o.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('crypto-protection-means','is-crypto-description')">＋</button></div></div>
 <div class="field"><span>Получение событий в SIEM</span><select id="is-siem"><option value="false" ${!item.siem_enabled?'selected':''}>Нет</option><option value="true" ${item.siem_enabled?'selected':''}>Да</option></select></div>`;
 renderISDetails();document.getElementById('modal').classList.add('show');
 markFormOpened();
}
function renderISDetails(){
 const e=window.isEditor;if(!e)return;
 document.getElementById('is-departments').innerHTML=e.details.departments.map((x,i)=>`<div class="nested-row"><select data-is-dep="${i}" onchange="syncISDetails()"><option value="">— выберите подразделение —</option>${e.deps.map(d=>`<option value="${esc(d.id)}" ${d.id===x.department_id?'selected':''}>${esc(lookupLabel('departments',d))}</option>`).join('')}</select><button type="button" class="btn gray" onclick="openQuickModal('departments','is-department')">＋ Новое</button><button type="button" class="btn red" onclick="removeISItem('departments',${i})">Удалить</button></div>`).join('')||'<div class="muted">Не добавлено</div>';
 document.getElementById('is-protocols').innerHTML=e.details.protocols.map((x,i)=>`<div class="nested-row four"><div class="lookup-row"><select data-is-prot="${i}" data-k="protocol_catalog_id"><option value="">— протокол / порт —</option>${e.protocolCatalogs?.map(o=>`<option value="${esc(o.id)}" ${o.id===x.protocol_catalog_id?'selected':''}>${esc(`${o.port} / ${o.protocol_type}`)}</option>`).join('')||''}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('protocol-port-catalog','is-protocol-catalog',${i})">＋</button></div><input data-is-prot="${i}" data-k="description" placeholder="Описание" value="${esc(x.description||'')}"><button type="button" class="btn red" onclick="removeISItem('protocols',${i})">Удалить</button></div>`).join('')||'<div class="muted">Не добавлено</div>';
 document.getElementById('is-sources').innerHTML=e.details.sources.map((x,i)=>{const type=x.source_type||'manual';const deviceOptions=e.devices.map(d=>`<option value="${esc(d.id)}" ${d.id===x.physical_device_id?'selected':''}>${esc(lookupLabel('devices',d))}</option>`).join('');const vms=[...e.vms].sort((a,b)=>{const am=(x.physical_device_id&&a.physical_device_id===x.physical_device_id)?0:1;const bm=(x.physical_device_id&&b.physical_device_id===x.physical_device_id)?0:1;return am-bm;}).map(v=>`<option value="${esc(v.id)}" ${v.id===x.virtual_machine_id?'selected':''}>${esc(lookupLabel('vms',v))}</option>`).join('');const contOptions=e.containers.map(c=>`<option value="${esc(c.id)}" ${c.id===x.container_id?'selected':''}>${esc(lookupLabel('containers',c))}</option>`).join('');return `<div class="nested-row is-source-row"><select data-is-source="${i}" data-k="source_type" onchange="onISSourceTypeChanged(${i})"><option value="manual" ${type==='manual'?'selected':''}>Вручную</option><option value="device" ${type==='device'?'selected':''}>Физический сервер / оборудование</option><option value="vm" ${type==='vm'?'selected':''}>Виртуальная машина</option><option value="container" ${type==='container'?'selected':''}>Контейнер</option></select><select data-is-source="${i}" data-k="physical_device_id" onchange="onISSourceDeviceChanged(${i})" ${type==='device'||type==='vm'?'':'disabled'}><option value="">— физический сервер —</option>${deviceOptions}</select><select data-is-source="${i}" data-k="virtual_machine_id" onchange="onISSourceVMChanged(${i})" ${type==='vm'?'':'disabled'}><option value="">— ВМ —</option>${vms}</select><select data-is-source="${i}" data-k="container_id" ${type==='container'?'':'disabled'}><option value="">— контейнер —</option>${contOptions}</select><input data-is-source="${i}" data-k="ip_address" placeholder="${type==='manual'?'IP-адрес (можно несколько через запятую)':'IP берется из выбранного оборудования/ВМ'}" value="${esc(x.ip_address||'')}" ${type==='manual'?'':'disabled'}><input data-is-source="${i}" data-k="purpose" placeholder="Назначение" value="${esc(x.purpose||'')}"><input data-is-source="${i}" data-k="role" placeholder="Роль в ИС" value="${esc(x.role||'')}"><label><input type="checkbox" data-is-source="${i}" data-k="external_interaction" ${x.external_interaction?'checked':''}> Внешнее</label><button type="button" class="btn red" onclick="removeISItem('sources',${i})">Удалить</button></div>`}).join('')||'<div class="muted">Не добавлено</div>';
 document.getElementById('is-placement-assets').innerHTML=e.details.placement_assets.map((x,i)=>`<div class="nested-row"><select data-is-pa="${i}"><option value="">— выберите —</option>${e.placementAssetsCatalog.map(p=>`<option value="${esc(p.id)}" ${p.id===x.placement_asset_id?'selected':''}>${esc(p.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('placement-assets','is-placement-asset')">＋ Новое</button><button type="button" class="btn red" onclick="removeISItem('placement_assets',${i})">Удалить</button></div>`).join('')||'<div class="muted">Не добавлено</div>';
}
function addISDepartment(){syncISDetails();window.isEditor.details.departments.push({department_id:''});renderISDetails()}
function addISProtocol(){syncISDetails();window.isEditor.details.protocols.push({protocol:'',port:null,protocol_catalog_id:'',description:''});renderISDetails()}
async function addISSource(){syncISDetails();window.isEditor.details.sources.push({source_type:'manual',physical_device_id:null,virtual_machine_id:null,container_id:null,ip_address:'',purpose:'',role:'',external_interaction:false});if(!window.isEditor.protocolCatalogs)window.isEditor.protocolCatalogs=(await get(api+'/resources/protocol-port-catalog?limit=1000')).items;renderISDetails()}
function addISPlacementAsset(){syncISDetails();window.isEditor.details.placement_assets.push({placement_asset_id:''});renderISDetails()}
function renderISSupportMethodOptions(){const sel=document.getElementById('is-support-method');const e=window.isEditor;if(!sel||!e)return;const current=sel.value;sel.innerHTML='<option value="">— не выбрано —</option>'+e.supportMethods.map(o=>`<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('');sel.value=current;}
function removeISItem(key,i){window.isEditor.details[key].splice(i,1);renderISDetails()}
async function onISSourceTypeChanged(i){syncISDetails();const x=window.isEditor.details.sources[i];x.physical_device_id=null;x.virtual_machine_id=null;x.container_id=null;x.ip_address='';renderISDetails()}
async function onISSourceDeviceChanged(i){syncISDetails();const e=window.isEditor,x=e.details.sources[i],dev=document.querySelector(`[data-is-source="${i}"][data-k="physical_device_id"]`)?.value||'';x.physical_device_id=dev||null;x.virtual_machine_id=null;renderISDetails()}
async function onISSourceVMChanged(i){syncISDetails();const e=window.isEditor,x=e.details.sources[i],vm=document.querySelector(`[data-is-source="${i}"][data-k="virtual_machine_id"]`)?.value||'';x.virtual_machine_id=vm||null;x.source_type='vm';if(vm){const obj=e.vms.find(v=>v.id===vm);x.physical_device_id=obj?.physical_device_id||null;}renderISDetails()}
function syncISDetails(){const e=window.isEditor;if(!e)return;document.querySelectorAll('[data-is-dep]').forEach(el=>{const i=+el.dataset.isDep;if(e.details.departments[i])e.details.departments[i].department_id=el.value});document.querySelectorAll('[data-is-prot]').forEach(el=>{const i=+el.dataset.isProt,k=el.dataset.k;if(e.details.protocols[i]){e.details.protocols[i][k]=el.value;if(k==='protocol_catalog_id'){const cat=e.protocolCatalogs?.find(x=>x.id===el.value);if(cat){e.details.protocols[i].protocol=cat.protocol_type;e.details.protocols[i].port=cat.port;}}}});document.querySelectorAll('[data-is-source]').forEach(el=>{const i=+el.dataset.isSource,k=el.dataset.k;if(!e.details.sources[i])return;if(el.type==='checkbox'){e.details.sources[i][k]=el.checked;return;}const fkKeys=['physical_device_id','virtual_machine_id','container_id'];e.details.sources[i][k]=(fkKeys.includes(k)&&el.value==='')?null:el.value;});document.querySelectorAll('[data-is-pa]').forEach(el=>{const i=+el.dataset.isPa;if(e.details.placement_assets[i])e.details.placement_assets[i].placement_asset_id=el.value});}
async function saveInformationSystemForm(){syncISDetails();const e=window.isEditor;const data={name:document.getElementById('is-name').value.trim(),description:document.getElementById('is-description').value||null,purpose:document.getElementById('is-purpose').value||null,localization:document.getElementById('is-localization').value||null,support_organization_id:document.getElementById('is-support-org').value||null,support_method_id:document.getElementById('is-support-method').value||null,process_description:document.getElementById('is-process').value||null,crypto_protection_enabled:document.getElementById('is-crypto').value==='true',crypto_protection_description_id:document.getElementById('is-crypto-description').value||null,siem_enabled:document.getElementById('is-siem').value==='true'};if(!data.name)return notify('Укажите наименование ИС.','error');try{const saved=await get(api+`/resources/information-systems${editingId?'/'+editingId:''}`,{method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const clean={departments:e.details.departments.filter(x=>x.department_id),ips:[],protocols:e.details.protocols.filter(x=>x.protocol_catalog_id||x.protocol?.trim()).map(x=>({...x,protocol_catalog_id:x.protocol_catalog_id||null})),devices:[],vms:[],containers:[],sources:e.details.sources.filter(x=>x.source_type==='manual'?x.ip_address?.trim():true),placement_assets:e.details.placement_assets.filter(x=>x.placement_asset_id)};await get(api+`/resources/information-systems/${saved.id}/details`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(clean)});closeModal(true);await renderList();}catch(err){notifyError(err)}}
async function openForm(id=''){
 editingId=id;
 if(resource==='device-types'){await openDeviceTypeForm(id);return;}
 if(resource==='connections'){await openConnectionForm(id);return;}
 if(resource==='interfaces'){await openInterfaceForm(id);return;}
 if(resource==='information-systems'){await openInformationSystemForm(id);return;}
 if(resource==='vlans'){await openVlanForm(id);return;}
 let item=id?await get(api+`/resources/${resource}/${id}`):{};
 if(resource==='vms') window._deviceTypes=(await get(api+'/resources/device-types?limit=1000')).items;
 document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+schema.name;
 let fields=schema.columns.filter(c=>!['id','created_at','updated_at'].includes(c.name)&&!(resource==='information-systems'&&['number','type','status'].includes(c.name))&&!(resource==='vms'&&['hypervisor_os_id','status'].includes(c.name))&&!(resource==='devices'&&['management_port','management_ip','physical_port_count','management_interface','management_ips','interface_count'].includes(c.name)));
 let html=[];for(const c of fields)html.push(await fieldHtml(c,item[c.name],item));
 if(resource==='devices'){html.push(`<div id="interfaceEditor" class="field full"></div>`);html.push(`<div id="deviceOpenPortsEditor" class="field full"></div>`);html.push(`<div id="deviceVlanEditor" class="field full"></div>`);}
 if(resource==='vms'){html.push(`<div id="vmIpEditor" class="field full"></div>`);html.push(`<div id="vmOpenPortsEditor" class="field full"></div>`);html.push(`<div id="vmSoftwareEditor" class="field full"></div>`);}
 document.getElementById('formGrid').innerHTML=html.join('');document.getElementById('modal').classList.add('show');
 if(resource==='devices'){setupDeviceLocationCascades(item);await Promise.all([loadInterfaceEditor(id),loadDeviceOpenPortsEditor(id),loadDeviceVlanEditor(id,item.device_type_id)]);}
 if(resource==='vms'){await loadVMIPEditor(id);await loadVMOpenPortsEditor(id);await loadVMSoftwareEditor(id);}
 markFormOpened();
}
// Общий helper для вложенных списков-редакторов (VLAN устройства, IP интерфейсов, IP ВМ,
// открытые порты ВМ и т.п. — раньше каждый такой список отдельно реализовывал одинаковые
// sync/render/add/remove, что уже приводило к однотипным багам, независимо чинившимся в разных
// копиях. stateGetter должен возвращать ту же самую (мутируемую) ссылку на массив каждый раз —
// тогда push/splice внутри helper'а меняют его "на месте", и существующий код, хранящий эту
// ссылку в глобальной переменной, продолжает работать без изменений.
async function openDeviceTypeForm(id=''){
 const item=id?await get(api+`/resources/device-types/${id}`):{};
 const vlans=(await get(api+'/resources/vlans?limit=1000')).items;
 const links=id?(await get(api+`/resources/device-type-vlans?limit=1000`)).items.filter(x=>x.device_type_id===id):[];
 const selected=new Set(links.map(x=>x.vlan_id));
 document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+'Тип устройства';
 document.getElementById('formGrid').innerHTML=`<label class="field full"><span>Наименование *</span><input id="device-type-name" required value="${esc(item.name||'')}"></label><div class="field full"><span>VLAN, разрешенные для этого типа оборудования</span><div class="lookup-row"><select id="device-type-vlan"><option value="">— выберите VLAN —</option>${vlans.map(v=>`<option value="${esc(v.id)}">${esc(v.vlan_id+' — '+v.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('vlans','device-type-vlan')">＋</button></div><div id="device-type-vlan-list" class="nested-list">${[...selected].map(v=>{const o=vlans.find(x=>x.id===v);return `<div class="nested-row"><span>${esc(o?o.vlan_id+' — '+o.name:v)}</span><button type="button" class="btn red" onclick="removeDeviceTypeVlan('${esc(v)}')">Удалить</button></div>`}).join('')||'<div class="muted">VLAN не назначены</div>'}</div><button type="button" class="btn gray" onclick="addDeviceTypeVlan()">+ VLAN</button></div>`;
 window.deviceTypeEditor={id,selected,vlans};document.getElementById('modal').classList.add('show');
}
function renderDeviceTypeVlanList(){const e=window.deviceTypeEditor;if(!e)return;const box=document.getElementById('device-type-vlan-list');box.innerHTML=[...e.selected].map(v=>{const o=e.vlans.find(x=>x.id===v);return `<div class="nested-row"><span>${esc(o?o.vlan_id+' — '+o.name:v)}</span><button type="button" class="btn red" onclick="removeDeviceTypeVlan('${esc(v)}')">Удалить</button></div>`}).join('')||'<div class="muted">VLAN не назначены</div>';}
function addDeviceTypeVlan(){const e=window.deviceTypeEditor,v=document.getElementById('device-type-vlan')?.value;if(v)e.selected.add(v);renderDeviceTypeVlanList();}
function removeDeviceTypeVlan(v){window.deviceTypeEditor?.selected.delete(v);renderDeviceTypeVlanList();}
async function openVlanForm(id=''){
 const item=id?await get(api+`/resources/vlans/${id}`):{};
 document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+'VLAN';
 document.getElementById('formGrid').innerHTML=`<label class="field"><span>VLAN ID *</span><input type="number" min="1" max="4094" id="vlan-vlan_id" required value="${esc(item.vlan_id??'')}"></label><label class="field"><span>VLAN Name *</span><input id="vlan-name" required value="${esc(item.name??'')}"></label><label class="field full"><span>Описание</span><textarea id="vlan-description">${esc(item.description??'')}</textarea></label>`;
 document.getElementById('modal').classList.add('show');
}
async function saveVlanForm(){
 const vlanIdValue=document.getElementById('vlan-vlan_id')?.value||'';
 const name=document.getElementById('vlan-name')?.value.trim()||'';
 if(!vlanIdValue||!name)return notify('Укажите VLAN ID и VLAN Name.','error');
 const data={vlan_id:Number(vlanIdValue),name,description:document.getElementById('vlan-description').value||null};
 try{
   await get(api+`/resources/vlans${editingId?'/'+editingId:''}`,{method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
   closeModal(true);await renderVlanDashboard();
 }catch(e){notifyError(e)}
}
async function saveDeviceTypeForm(){const e=window.deviceTypeEditor,name=document.getElementById('device-type-name').value.trim();if(!name)return notify('Укажите наименование типа устройства.','error');try{const saved=await get(api+`/resources/device-types${e.id?'/'+e.id:''}`,{method:e.id?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});const old=(await get(api+'/resources/device-type-vlans?limit=1000')).items.filter(x=>x.device_type_id===saved.id);for(const x of old)await get(api+`/resources/device-type-vlans/${x.id}`,{method:'DELETE'});for(const vlan_id of e.selected)await get(api+'/resources/device-type-vlans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_type_id:saved.id,vlan_id})});closeModal(true);await renderList();}catch(err){notifyError(err)}}
async function fieldHtml(c,v,item={}){
 const label=labels[c.name]||c.name;
 if(resource==='devices'&&c.name==='status'){
   const opts=[['','— не выбрано —'],['В эксплуатации','В эксплуатации'],['Резерв','Резерв'],['На обслуживании','На обслуживании'],['Неисправно','Неисправно'],['Выведено из эксплуатации','Выведено из эксплуатации'],['Списано','Списано']];
   return `<label class="field"><span>${label}</span><select name="status">${opts.map(([a,b])=>`<option value="${esc(a)}" ${a===(v??'')?'selected':''}>${esc(b)}</option>`).join('')}</select></label>`;
 }
 if(resource==='devices'&&c.name==='manufacturer_id') return '';
 if(resource==='devices'&&c.name==='device_type_id') return '';
 if(resource==='devices'&&c.name==='model_id'){
   const models=(await get(api+'/resources/device-models?limit=1000')).items;
   const manufacturers=(await get(api+'/resources/manufacturers?limit=1000')).items;
   const types=(await get(api+'/resources/device-types?limit=1000')).items;
   const mMap=Object.fromEntries(manufacturers.map(x=>[x.id,x.name])); const tMap=Object.fromEntries(types.map(x=>[x.id,x.name]));
   const groups={}; models.forEach(o=>{const key=`${o.manufacturer_id||''}|${o.device_type_id||''}`;(groups[key]??=[]).push(o)});
   const selected=v??'';
   const grouped=Object.entries(groups).map(([key,items])=>{const [mid,tid]=key.split('|');return `<optgroup label="${esc(`${mMap[mid]||'Без производителя'} → ${tMap[tid]||'Без типа'}`)}">${items.map(o=>`<option value="${esc(o.id)}" ${o.id===selected?'selected':''}>${esc(o.model)}</option>`).join('')}</optgroup>`}).join('');
   // If a model is selected, its own manufacturer/type are the source of truth (the catalog entry may have
   // been recategorized after this device was created, which is exactly what caused the "модель не
   // соответствует типу" error even without touching this field at all).
   const selectedModel=models.find(x=>x.id===selected);
   const manufacturer=selectedModel?(selectedModel.manufacturer_id||''):(item.manufacturer_id||''); const deviceType=selectedModel?(selectedModel.device_type_id||''):(item.device_type_id||'');
   return `<label class="field full"><span>Оборудование (Производитель → Тип устройства → Модель)</span><div class="lookup-row"><select id="field-model_id" name="model_id" onchange="onDeviceModelChanged()"><option value="">— выберите оборудование —</option>${grouped}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('device-models','model_id')">＋</button></div><input type="hidden" id="field-manufacturer_id" name="manufacturer_id" value="${esc(manufacturer)}"><input type="hidden" id="field-device_type_id" name="device_type_id" value="${esc(deviceType)}"></label>`;
 }
 if(resource==='devices'&&c.name==='embedded_os_id'){
   const opts=(await get(api+'/resources/embedded-os?limit=1000')).items;
   return `<label class="field"><span>Встроенная ОС</span><div class="lookup-row"><select id="field-embedded_os_id" name="embedded_os_id"><option value="">— не выбрано —</option>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===v?'selected':''}>${esc([o.name,o.version].filter(Boolean).join(' '))}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('embedded-os','embedded_os_id')">＋</button></div></label>`;
 }
 if(resource==='devices'&&c.name==='operating_system_id'){
   const opts=(await get(api+'/resources/operating-systems?limit=1000')).items;
   return `<label class="field"><span>ОС</span><div class="lookup-row"><select id="field-operating_system_id" name="operating_system_id" onchange="onDeviceOSChanged()"><option value="">— не выбрано —</option>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===v?'selected':''}>${esc([o.name,o.version].filter(Boolean).join(' '))}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('operating-systems','operating_system_id')">＋</button></div></label>`;
 }
 if(resource==='devices'&&c.name==='building_id'){
   const buildings=(await get(api+'/resources/buildings?limit=1000')).items;
   const rooms=(await get(api+'/resources/rooms?limit=1000')).items.filter(x=>!item.building_id||x.building_id===item.building_id);
   const racks=(await get(api+'/resources/racks?limit=1000')).items.filter(x=>!item.room_id||x.room_id===item.room_id);
   const selectedRack=racks.find(x=>x.id===item.rack_id);
   const posLabel='Позиция в стойке'+(selectedRack?.height_u?` (1–${selectedRack.height_u} U)`:'');
   return `<div class="field full location-group"><span>Размещение</span><div class="location-grid">
   <label class="field"><span>Здание</span><div class="lookup-row"><select id="field-building_id" name="building_id" onchange="onDeviceBuildingChanged()"><option value="">— выберите здание —</option>${buildings.map(x=>`<option value="${esc(x.id)}" ${x.id===item.building_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('buildings','building_id')">＋</button></div></label>
   <label class="field"><span>Помещение</span><div class="lookup-row"><select id="field-room_id" name="room_id" onchange="onDeviceRoomChanged()"><option value="">— выберите помещение —</option>${rooms.map(x=>`<option value="${esc(x.id)}" ${x.id===item.room_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('rooms','room_id')">＋</button></div></label>
   <label class="field"><span>Стойка</span><div class="lookup-row"><select id="field-rack_id" name="rack_id" onchange="onDeviceRackChanged()"><option value="">— выберите стойку —</option>${racks.map(x=>`<option value="${esc(x.id)}" ${x.id===item.rack_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('racks','rack_id')">＋</button></div></label>
   <label class="field"><span id="field-rack_position-label">${posLabel}</span><input id="field-rack_position" name="rack_position" type="number" min="1" ${selectedRack?.height_u?`max="${selectedRack.height_u}"`:''} placeholder="Например, 10" value="${esc(item.rack_position??'')}" ${item?.rack_id?'':'disabled'}></label>
   </div></div>`;
 }
 if(resource==='devices'&&['room_id','rack_id','rack_position'].includes(c.name))return '';
 if(resource==='open-ports'&&c.name==='owner_type'){
   const opts=[['physical_device','Физическое устройство'],['virtual_machine','Виртуальная машина']];
   return `<label class="field"><span>${label} *</span><select id="field-owner_type" name="owner_type" required onchange="onOpenPortOwnerTypeChanged()"><option value="">— выберите тип владельца —</option>${opts.map(([a,b])=>`<option value="${esc(a)}" ${a===(v??'')?'selected':''}>${esc(b)}</option>`).join('')}</select></label>`;
 }
 if(resource==='open-ports'&&c.name==='owner_id'){
   const ownerType=v?item.owner_type:'';
   const rr=ownerType==='virtual_machine'?'vms':ownerType==='physical_device'?'devices':'';
   const opts=rr?(await get(api+`/resources/${rr}?limit=1000`)).items:[];
   return `<label class="field"><span>${label} *</span><select id="field-owner_id" name="owner_id" required ${rr?'':'disabled'}><option value="">${rr?'— выберите —':'— сначала выберите тип владельца —'}</option>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===v?'selected':''}>${esc(lookupLabel(rr,o))}</option>`).join('')}</select></label>`;
 }
 if(resource==='open-ports'&&c.name==='protocol_catalog_id'){
   const opts=(await get(api+'/resources/protocol-port-catalog?limit=1000')).items;
   return `<label class="field"><span>Протокол / порт из справочника</span><div class="lookup-row"><select id="field-protocol_catalog_id" name="protocol_catalog_id" onchange="onOpenPortCatalogChanged()"><option value="">— не выбрано —</option>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===v?'selected':''}>${esc(`${o.port} / ${o.protocol_type}`)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('protocol-port-catalog','protocol_catalog_id')">＋</button></div></label>
   <label class="field"><span>Порт *</span><input type="number" min="1" max="65535" id="field-port" name="port" required value="${esc(item.port??'')}"></label>
   <label class="field"><span>Протокол</span><input id="field-protocol" name="protocol" value="${esc(item.protocol??'')}"></label>`;
 }
 if(resource==='open-ports'&&['port','protocol'].includes(c.name))return '';
 if(c.type==='BOOLEAN')return `<label class="field"><span>${label}</span><select name="${c.name}"><option value="false" ${v===false?'selected':''}>Нет</option><option value="true" ${v===true?'selected':''}>Да</option></select></label>`;
 if(c.foreign_key){
   const target=c.foreign_key.split('.')[0],rr=resourceMap[target];
   if(rr){
     let opts=(await get(api+`/resources/${rr}?limit=1000`)).items;
     if(resource==='devices'&&c.name==='model_id'){const man=document.getElementById('field-manufacturer_id')?.value||item.manufacturer_id||'';const typ=document.getElementById('field-device_type_id')?.value||item.device_type_id||'';opts=opts.filter(o=>(!man||o.manufacturer_id===man)&&(!typ||o.device_type_id===typ));}
     if(resource==='vms'&&c.name==='physical_device_id'){opts=opts.filter(o=>{const dt=(window._deviceTypes||[]).find(t=>t.id===o.device_type_id);const n=(dt?.name||'').toLowerCase();return n.includes('сервер')||n.includes('система хранения')||n.includes('storage')});}
     let selected=v??'';
     const onchange=resource==='devices'&&c.name==='manufacturer_id'?' onchange="onDeviceCatalogChanged()"':resource==='devices'&&c.name==='device_type_id'?' onchange="onDeviceCatalogChanged()"':'';
     const canQuick=['buildings','rooms','racks','device-types','manufacturers','device-models','os-categories','operating-systems','interface-types','interface-speeds','connection-types'].includes(rr);
     const add=canQuick?`<button type="button" class="btn gray inline-add" onclick="openQuickModal('${rr}','${c.name}')">＋</button>`:'';
     return `<label class="field"><span>${label}${c.nullable?'':' *'}</span><div class="lookup-row"><select id="field-${c.name}" name="${c.name}" ${c.nullable?'':'required'}${onchange}>${c.nullable?'<option value="">— не выбрано —</option>':''}${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===selected?'selected':''}>${esc(lookupLabel(rr,o))}</option>`).join('')}</select>${add}</div></label>`;
   }
 }
 const full=String(c.type).toUpperCase().includes('TEXT')||c.name.includes('description')||c.name.includes('purpose')||c.name.includes('process');
 const type=String(c.type).toUpperCase().includes('INTEGER')?'number':'text';
 return full?`<label class="field full"><span>${label}${c.nullable?'':' *'}</span><textarea name="${c.name}" ${c.nullable?'':'required'}>${esc(v??'')}</textarea></label>`:`<label class="field"><span>${label}${c.nullable?'':' *'}</span><input type="${type}" name="${c.name}" value="${esc(v??'')}" ${c.nullable?'':'required'}></label>`;
}
async function onOpenPortOwnerTypeChanged(){
 const typeField=document.getElementById('field-owner_type'),idField=document.getElementById('field-owner_id');
 if(!typeField||!idField)return;
 const rr=typeField.value==='virtual_machine'?'vms':typeField.value==='physical_device'?'devices':'';
 if(!rr){idField.innerHTML='<option value="">— сначала выберите тип владельца —</option>';idField.disabled=true;return;}
 const opts=(await get(api+`/resources/${rr}?limit=1000`)).items;
 idField.innerHTML='<option value="">— выберите —</option>'+opts.map(o=>`<option value="${esc(o.id)}">${esc(lookupLabel(rr,o))}</option>`).join('');
 idField.disabled=false;
}
function onOpenPortCatalogChanged(){
 const sel=document.getElementById('field-protocol_catalog_id'),portField=document.getElementById('field-port'),protoField=document.getElementById('field-protocol');
 if(!sel||!portField||!protoField)return;
 const opt=sel.selectedOptions[0];
 if(!opt||!opt.value)return;
 const [port,protocolType]=opt.textContent.split(' / ');
 if(port)portField.value=port.trim();
 if(protocolType)protoField.value=protocolType.trim();
}
function setupDeviceLocationCascades(){updateRackPositionState();}
function updateRackPositionState(){const rack=document.getElementById('field-rack_id'),pos=document.getElementById('field-rack_position');if(pos)pos.disabled=!(rack&&rack.value);}
async function onDeviceBuildingChanged(){const b=document.getElementById('field-building_id')?.value||'',room=document.getElementById('field-room_id'),rack=document.getElementById('field-rack_id'),pos=document.getElementById('field-rack_position');if(room){const items=(await get(api+'/resources/rooms?limit=1000')).items.filter(x=>!b||x.building_id===b);room.innerHTML='<option value="">— не выбрано —</option>'+items.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');}if(rack)rack.innerHTML='<option value="">— не выбрано —</option>';if(pos){pos.value='';pos.disabled=true;}}
async function onDeviceRoomChanged(){const r=document.getElementById('field-room_id')?.value||'',rack=document.getElementById('field-rack_id'),pos=document.getElementById('field-rack_position');if(rack){const items=(await get(api+'/resources/racks?limit=1000')).items.filter(x=>!r||x.room_id===r);rack.innerHTML='<option value="">— не выбрано —</option>'+items.map(x=>`<option value="${esc(x.id)}">${esc(x.name)}</option>`).join('');}if(pos){pos.value='';pos.disabled=true;}}
async function onDeviceRackChanged(){
 updateRackPositionState();
 const rackSel=document.getElementById('field-rack_id'),pos=document.getElementById('field-rack_position'),label=document.getElementById('field-rack_position-label');
 if(!rackSel||!pos)return;
 if(!rackSel.value){pos.removeAttribute('max');if(label)label.textContent='Позиция в стойке';return;}
 const rack=await get(api+'/resources/racks/'+rackSel.value);
 if(rack.height_u){
   pos.max=rack.height_u;if(label)label.textContent=`Позиция в стойке (1–${rack.height_u} U)`;
   if(pos.value&&Number(pos.value)>rack.height_u)pos.value='';
 }else{pos.removeAttribute('max');if(label)label.textContent='Позиция в стойке';}
}
async function onDeviceOSChanged(){
 const id=document.getElementById('field-operating_system_id')?.value||''; const version=document.getElementById('field-os-version');
 if(!version){return;}
 if(!id){version.value='';return;}
 const os=await get(api+'/resources/operating-systems/'+id); version.value=os.version||'';
}
async function onDeviceModelChanged(){
 const sel=document.getElementById('field-model_id'),mf=document.getElementById('field-manufacturer_id'),tf=document.getElementById('field-device_type_id');
 if(!sel)return;
 let deviceTypeId='';
 if(sel.value){
   const models=(await get(api+'/resources/device-models?limit=1000')).items;
   const m=models.find(x=>x.id===sel.value);
   if(m){if(mf)mf.value=m.manufacturer_id||'';if(tf)tf.value=m.device_type_id||'';deviceTypeId=m.device_type_id||'';}
 }else{
   if(mf)mf.value='';if(tf)tf.value='';
 }
 if(document.getElementById('interfaceEditor')){await Promise.all([loadInterfaceEditor(editingId||''),loadDeviceVlanEditor(editingId||'',deviceTypeId)]);}
}
async function onDeviceCatalogChanged(){const mf=document.getElementById('field-manufacturer_id'),tf=document.getElementById('field-device_type_id'),model=document.getElementById('field-model_id');if(!model)return;const m=mf?.value||'',t=tf?.value||'',current=model.value;const opts=(await get(api+'/resources/device-models?limit=1000')).items.filter(x=>(!m||x.manufacturer_id===m)&&(!t||x.device_type_id===t));model.innerHTML='<option value="">— не выбрано —</option>'+opts.map(x=>`<option value="${esc(x.id)}">${esc(lookupLabel('device-models',x))}</option>`).join('');if(opts.some(x=>x.id===current))model.value=current;;if(document.getElementById('interfaceEditor')){await Promise.all([loadInterfaceEditor(editingId||''),loadDeviceVlanEditor(editingId||'',t)]);}}
async function loadInterfaceCatalogs(){interfaceSpeedOptions=(await get(api+'/resources/interface-speeds?limit=1000')).items;interfaceTypeOptions=(await get(api+'/resources/interface-types?limit=1000')).items;}
function optionHtml(items,current){return '<option value="">— не выбрано —</option>'+items.map(o=>`<option value="${esc(o.id)}" ${o.id===current?'selected':''}>${esc(o.name)}</option>`).join('');}
function interfaceTypeOptionsHtml(current){return optionHtml(interfaceTypeOptions,current)}
function speedOptionsHtml(current){return optionHtml(interfaceSpeedOptions,current)}
async function loadInterfaceEditor(deviceId){
 await loadInterfaceCatalogs();
 let deviceTypeId=document.getElementById('field-device_type_id')?.value||'';
 if(deviceId){const d=await get(api+`/resources/devices/${deviceId}`);deviceTypeId=d.device_type_id;}
 const allowed=deviceTypeId?(await get(api+`/resources/device-type-vlans?device_type_id=${deviceTypeId}&limit=1000`)).items:[];
 const vlans=(await get(api+'/resources/vlans?limit=1000')).items;
 const catalogVlans=vlans.filter(v=>allowed.some(a=>a.vlan_id===v.id));
 // VLAN на порту must also offer whatever is actually assigned to this device in "VLAN устройства",
 // not only the (optional, device-type-level) catalog restriction — otherwise a device's own VLANs
 // never appear as selectable options when editing it.
 const assignedLinks=deviceId?(await get(api+`/resources/device-vlans?physical_device_id=${deviceId}&limit=1000`)).items:[];
 const assignedVlans=assignedLinks.map(x=>vlans.find(v=>v.id===x.vlan_id)).filter(Boolean);
 window.currentDeviceTypeVlanOptions=catalogVlans;
 deviceVlanOptions=[...catalogVlans];
 for(const v of assignedVlans) if(!deviceVlanOptions.some(x=>x.id===v.id)) deviceVlanOptions.push(v);
 interfaceRows=deviceId?(await get(api+`/resources/interfaces?limit=1000`)).items.filter(x=>x.physical_device_id===deviceId):[];
 const allIfaceIps=(await get(api+'/resources/interface-ips?limit=1000')).items;
 const allIfaceVlans=(await get(api+'/resources/interface-vlans?limit=1000')).items;
 for(const x of interfaceRows){x.ips=allIfaceIps.filter(ip=>ip.interface_id===x.id);x.vlan_ids=allIfaceVlans.filter(v=>v.interface_id===x.id).map(v=>v.vlan_id);}
 renderInterfaceEditor();
}
// Keeps "VLAN на порту" options (and any checkboxes already ticked) in sync whenever VLAN устройства changes.
function syncDeviceVlanOptionsFromRows(){
 const catalog=window.currentDeviceTypeVlanOptions||[];
 const known=window.currentDeviceVlanOptions||deviceVlanOptions||[];
 const assigned=deviceVlanRows.map(x=>known.find(v=>v.id===x.vlan_id)).filter(Boolean);
 const merged=[...catalog];
 for(const v of assigned) if(!merged.some(x=>x.id===v.id)) merged.push(v);
 const removedIds=deviceVlanOptions.filter(v=>!merged.some(m=>m.id===v.id)).map(v=>v.id);
 deviceVlanOptions=merged;
 if(removedIds.length) for(const row of interfaceRows) if(row.vlan_ids) row.vlan_ids=row.vlan_ids.filter(id=>!removedIds.includes(id));
 renderInterfaceEditor();
}
function interfaceTemplateValue(t,n){return String(t||'').replaceAll('{n}',String(n)).replaceAll('{n0}',String(n).padStart(2,'0'));}
function renderInterfaceEditor(){
 const box=document.getElementById('interfaceEditor');if(!box)return;
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>Порты / интерфейсы</b><span class="muted">Управление отмечается на одном или нескольких интерфейсах. Все IP таких интерфейсов считаются IP управления.</span></div><div class="ie-generator"><label>Количество<input id="if-count" type="number" min="0" value="${interfaceRows.length}"></label><label>Шаблон имени<input id="if-name-template" value="eth{n}"></label><label>Тип по умолчанию<select id="if-type-template">${interfaceTypeOptionsHtml('')}</select></label><label>Скорость по умолчанию<select id="if-speed-template">${speedOptionsHtml('')}</select></label><button type="button" class="btn gray" onclick="generateInterfaces()">Сгенерировать</button><button type="button" class="btn gray" onclick="addInterfaceRow()">+ Интерфейс</button></div>${interfaceRows.length?bulkInterfaceEditHtml():''}<div class="interface-cards">${interfaceRows.map((x,i)=>interfaceCardHtml(x,i)).join('')}</div></div>`;
 box.querySelectorAll('[data-if]').forEach(el=>el.addEventListener('input',syncInterfaceRows));box.querySelectorAll('[data-if]').forEach(el=>el.addEventListener('change',syncInterfaceRows));
}
function bulkInterfaceEditHtml(){
 return `<div class="bulk-edit-bar"><b>Массовое редактирование</b>
 <label><input type="checkbox" id="if-bulk-select-all" onchange="toggleAllInterfaceSelection(this.checked)"> Выбрать все</label>
 <label>Тип интерфейса<select id="if-bulk-type"><option value="">— не менять —</option>${interfaceTypeOptionsHtml('')}</select></label>
 <label>Скорость<select id="if-bulk-speed"><option value="">— не менять —</option>${speedOptionsHtml('')}</select></label>
 <label>Управление<select id="if-bulk-management"><option value="">— не менять —</option><option value="true">Включить</option><option value="false">Выключить</option></select></label>
 <label>Передача данных<select id="if-bulk-data-transfer"><option value="">— не менять —</option><option value="true">Включить</option><option value="false">Выключить</option></select></label>
 <label class="full">VLAN на порту (будет добавлен к выбранным)<div class="vlan-checks">${sortedVlanOptions().map(v=>`<label><input type="checkbox" class="if-bulk-vlan" value="${esc(v.id)}"> ${esc(v.vlan_id+' — '+v.name)}</label>`).join('')||'<span class="muted">VLAN не назначены</span>'}</div></label>
 <button type="button" class="btn gray" onclick="applyBulkInterfaceEdit()">Применить к выбранным</button>
 </div>`;
}
function toggleAllInterfaceSelection(checked){document.querySelectorAll('.if-select').forEach(el=>{el.checked=checked;});}
function applyBulkInterfaceEdit(){
 syncInterfaceRows();
 const selected=Array.from(document.querySelectorAll('.if-select:checked')).map(el=>+el.dataset.ifSelect);
 if(!selected.length)return notify('Отметьте хотя бы один интерфейс галочкой "Выбрать".','error');
 const type=document.getElementById('if-bulk-type').value,speed=document.getElementById('if-bulk-speed').value,mgmt=document.getElementById('if-bulk-management').value,dataTransfer=document.getElementById('if-bulk-data-transfer').value;
 const vlanIds=Array.from(document.querySelectorAll('.if-bulk-vlan:checked')).map(el=>el.value);
 for(const i of selected){
   const row=interfaceRows[i];if(!row)continue;
   if(type)row.interface_type_id=type;
   if(speed)row.speed_id=speed;
   if(mgmt)row.is_management=mgmt==='true';
   if(dataTransfer)row.is_data_transfer=dataTransfer==='true';
   if(vlanIds.length)row.vlan_ids=Array.from(new Set([...(row.vlan_ids||[]),...vlanIds]));
 }
 renderInterfaceEditor();
}
function interfaceCardHtml(x,i){
 const ips=x.ips||[];
 return `<div class="interface-card"><div class="interface-card-head"><label class="if-select-label"><input type="checkbox" class="if-select" data-if-select="${i}"> Выбрать</label><b>Интерфейс ${i+1}</b><button type="button" class="btn red" onclick="removeInterfaceRow(${i})">Удалить</button></div><div class="interface-card-grid"><label class="field"><span>Имя</span><input data-if="${i}" data-k="name" value="${esc(x.name||'')}"></label><label class="field"><span>Тип</span><div class="lookup-row"><select data-if="${i}" data-k="interface_type_id">${interfaceTypeOptionsHtml(x.interface_type_id||'')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('interface-types','interface_type_id',${i})">＋</button></div></label><label class="field"><span>MAC</span><input data-if="${i}" data-k="mac_address" value="${esc(x.mac_address||'')}"></label><label class="field"><span>Скорость</span><div class="lookup-row"><select data-if="${i}" data-k="speed_id">${speedOptionsHtml(x.speed_id||'')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('interface-speeds','speed_id',${i})">＋</button></div></label><label class="field"><span>Управление</span><input type="checkbox" data-if="${i}" data-k="is_management" ${x.is_management?'checked':''}></label><label class="field"><span>Передача данных</span><input type="checkbox" data-if="${i}" data-k="is_data_transfer" ${x.is_data_transfer?'checked':''}></label><label class="field full"><span>VLAN на порту</span><div class="vlan-checks">${sortedVlanOptions().map(v=>`<label><input type="checkbox" data-vlan-if="${i}" value="${esc(v.id)}" ${(x.vlan_ids||[]).includes(v.id)?'checked':''}> ${esc(v.vlan_id+' — '+v.name)}</label>`).join('')||'<span class="muted">Для типа устройства VLAN не назначены</span>'}</div></label><label class="field full"><span>Описание</span><textarea data-if="${i}" data-k="description">${esc(x.description||'')}</textarea></label></div><div class="ip-editor"><div class="interface-card-head"><b>IP-адреса интерфейса</b><button type="button" class="btn gray" onclick="event.preventDefault(); event.stopPropagation(); addInterfaceIP(${i})">+ IP-адрес</button></div>${ips.map((ip,j)=>`<div class="ip-row"><input data-ip="${i}" data-j="${j}" data-k="ip_address" placeholder="IP-адрес" value="${esc(ip.ip_address||'')}"><input data-ip="${i}" data-j="${j}" data-k="prefix_length" type="number" min="0" max="128" placeholder="Префикс" value="${esc(ip.prefix_length??'')}"><input data-ip="${i}" data-j="${j}" data-k="purpose" placeholder="Назначение" value="${esc(ip.purpose||'')}"><button type="button" class="btn red" onclick="removeInterfaceIP(${i},${j})">Удалить</button></div>`).join('')||'<div class="muted">IP-адреса не добавлены</div>'}</div></div>`;
}
function syncInterfaceRows(){document.querySelectorAll('[data-vlan-if]').forEach(el=>{const i=+el.dataset.vlanIf;if(interfaceRows[i]){interfaceRows[i].vlan_ids=Array.from(document.querySelectorAll(`[data-vlan-if="${i}"]:checked`)).map(x=>x.value);}});document.querySelectorAll('[data-if]').forEach(el=>{const i=+el.dataset.if,k=el.dataset.k;if(interfaceRows[i])interfaceRows[i][k]=el.type==='checkbox'?el.checked:el.value;});document.querySelectorAll('[data-ip]').forEach(el=>{const i=+el.dataset.ip,j=+el.dataset.j,k=el.dataset.k;if(interfaceRows[i]?.ips?.[j])interfaceRows[i].ips[j][k]=el.value;});}
function addInterfaceIP(i){syncInterfaceRows();if(!interfaceRows[i])return;interfaceRows[i].ips=Array.isArray(interfaceRows[i].ips)?interfaceRows[i].ips:[];interfaceRows[i].ips.push({ip_address:'',prefix_length:'',purpose:''});renderInterfaceEditor();}
function removeInterfaceIP(i,j){syncInterfaceRows();interfaceRows[i].ips.splice(j,1);renderInterfaceEditor();}
function generateInterfaces(){syncInterfaceRows();const count=Math.max(0,+document.getElementById('if-count').value||0),nt=document.getElementById('if-name-template').value||'eth{n}',it=document.getElementById('if-type-template').value||'',sp=document.getElementById('if-speed-template').value||'';interfaceRows=Array.from({length:count},(_,i)=>({...interfaceRows[i],name:interfaceTemplateValue(nt,i+1),interface_type_id:it,speed_id:sp,ips:interfaceRows[i]?.ips||[]}));renderInterfaceEditor();}
function addInterfaceRow(){syncInterfaceRows();interfaceRows.push({name:'',interface_type_id:'',mac_address:'',speed_id:'',is_management:false,description:'',ips:[]});renderInterfaceEditor();}
function removeInterfaceRow(i){syncInterfaceRows();interfaceRows.splice(i,1);renderInterfaceEditor();}
async function loadDeviceVlanEditor(deviceId,deviceTypeId){
 const box=document.getElementById('deviceVlanEditor');if(!box)return;
 const all=(await get(api+'/resources/vlans?limit=1000')).items;
 const domains=(await get(api+'/resources/vlan-domains?limit=1000')).items;
 deviceVlanRows=deviceId?(await get(api+`/resources/device-vlans?physical_device_id=${deviceId}&limit=1000`)).items:[];
 const domainLinks=deviceId?(await get(api+`/resources/vlan-domain-devices?physical_device_id=${deviceId}&limit=1000`)).items:[];
 const memberDomains=new Set(domainLinks.map(x=>x.domain_id));
 const available=all.filter(v=>!v.domain_id||memberDomains.has(v.domain_id));
 window.currentDeviceVlanOptions=available;window.currentVlanDomains=domains;window.currentDeviceVlanAll=all;
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>VLAN устройства</b><span class="muted">VLAN может быть локальным для устройства или принадлежать общему домену. Один VLAN ID может иметь разные названия и описания на разных устройствах.</span></div><div id="device-vlan-list" class="nested-list"></div><div class="lookup-row"><button type="button" class="btn gray" onclick="showDeviceVlanAddMenu()">＋ VLAN</button><div id="device-vlan-add-menu" class="inline-menu" style="display:none"><button type="button" class="btn gray" onclick="openQuickModal('vlans','device-vlan-new')">Новый VLAN для устройства</button><button type="button" class="btn gray" onclick="createVlanDomainFromDevice()">Создать домен VLAN</button><button type="button" class="btn gray" onclick="copyVlanListFromDevice()">Скопировать VLAN с другого устройства</button></div></div></div>`;
 deviceVlanEditor.render();
}
function showDeviceVlanAddMenu(){const x=document.getElementById('device-vlan-add-menu');if(x)x.style.display=x.style.display==='none'?'flex':'none';}
function deviceVlanRowHtml(x,i,vlans,domains){
 return `<div class="nested-row vlan-device-row">
 <select data-dv="${i}" data-k="vlan_id"><option value="">— VLAN —</option>${vlans.map(v=>`<option value="${esc(v.id)}" ${v.id===x.vlan_id?'selected':''}>${esc(v.vlan_id+' — '+v.name+(v.domain_id?' ['+(domains.find(d=>d.id===v.domain_id)?.name||'домен')+']':''))}</option>`).join('')}</select>
 <input data-dv="${i}" data-k="ip_address" placeholder="IP VLAN" value="${esc(x.ip_address||'')}"><input data-dv="${i}" data-k="prefix_length" type="number" min="0" max="128" placeholder="Префикс" value="${esc(x.prefix_length??'')}"><label><input type="checkbox" data-dv="${i}" data-k="is_management" ${x.is_management?'checked':''}> Управление</label><button type="button" class="btn red" onclick="removeDeviceVlanRow(${i})">Удалить</button></div>`;
}
function deviceVlanRowHtmlAuto(x,i){
 const vlansList=window.currentDeviceVlanAll||window.currentDeviceVlanOptions||[];
 return deviceVlanRowHtml(x,i,vlansList,window.currentVlanDomains||[]);
}
function sortedVlanOptions(){return [...deviceVlanOptions].sort((a,b)=>(a.vlan_id??0)-(b.vlan_id??0));}
function sortDeviceVlanRowsByVlanId(rows){
 const vlansList=window.currentDeviceVlanAll||window.currentDeviceVlanOptions||[];
 const find=id=>vlansList.find(v=>v.id===id);
 return rows.map((x,i)=>[x,i]).sort((a,b)=>{
   const av=find(a[0].vlan_id),bv=find(b[0].vlan_id);
   return (av?av.vlan_id:Number.MAX_SAFE_INTEGER)-(bv?bv.vlan_id:Number.MAX_SAFE_INTEGER);
 });
}
const deviceVlanEditor=attachNestedListEditor(()=>deviceVlanRows,{
 htmlAttr:'dv', rowHtml:deviceVlanRowHtmlAuto, listId:'device-vlan-list', emptyMessage:'VLAN не назначены',
 sortRows:sortDeviceVlanRowsByVlanId,
 onAfterRemove:async removed=>{
   syncDeviceVlanOptionsFromRows();
   if(removed?.id&&editingId){try{await get(api+`/resources/device-vlans/${removed.id}`,{method:'DELETE'})}catch(e){/* уже удалено или устройство ещё не сохранено — игнорируем */}}
 },
});
function syncDeviceVlanRows(){deviceVlanEditor.sync();}
function renderDeviceVlanRows(){deviceVlanEditor.render();}
function removeDeviceVlanRow(i){deviceVlanEditor.remove(i);}
async function createVlanDomainFromDevice(){
 const name=prompt('Наименование домена VLAN:');if(!name)return;const description=prompt('Описание домена (необязательно):')||'';
 try{const d=await get(api+'/resources/vlan-domains',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,description,source_device_id:editingId,auto_sync:false})});
 await get(api+`/vlan-domains/${d.id}/members`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({physical_device_id:editingId})});
 window.currentVlanDomains=[...(window.currentVlanDomains||[]),d];showDeviceVlanAddMenu();notify('Домен создан и привязан к текущему устройству.','success');renderDeviceVlanRows();
 }catch(e){notifyError(e)}
}
async function copyVlanListFromDevice(){
 const devices=(await get(api+'/resources/devices?limit=1000')).items.filter(d=>d.id!==editingId);
 if(!devices.length)return notify('Нет других устройств.','error');
 const options=devices.map((d,i)=>`${i+1}. ${d.system_name||d.serial_number||d.id}`).join('\n');
 const n=Number(prompt('Выберите номер устройства-источника:\n'+options));if(!n||!devices[n-1])return;
 try{const r=await get(api+`/devices/${editingId}/vlan-copy`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_device_id:devices[n-1].id})});await loadDeviceVlanEditor(editingId,document.getElementById('field-device_type_id')?.value||'');notify(`Скопировано VLAN: ${r.assigned}`,'success');}catch(e){notifyError(e)}
}
async function saveDeviceVlans(deviceId){
 syncDeviceVlanRows();
 const old=(await get(api+`/resources/device-vlans?physical_device_id=${deviceId}&limit=1000`)).items;
 for(const x of old)await get(api+`/resources/device-vlans/${x.id}`,{method:'DELETE'});
 for(const x of deviceVlanRows){
   if(x.vlan_id)await get(api+'/resources/device-vlans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({physical_device_id:deviceId,vlan_id:x.vlan_id,ip_address:x.ip_address||null,prefix_length:x.prefix_length===''?null:Number(x.prefix_length),is_management:!!x.is_management,description:x.description||null})});
 }
}
async function saveDeviceInterfaces(deviceId){syncInterfaceRows();const payload={interfaces:interfaceRows.map(x=>({id:x.id||undefined,name:x.name||'',interface_type_id:x.interface_type_id||null,mac_address:x.mac_address||null,speed_id:x.speed_id||null,is_management:!!x.is_management,is_data_transfer:!!x.is_data_transfer,description:x.description||null,vlan_ids:x.vlan_ids||[],ips:(x.ips||[]).filter(ip=>ip.ip_address).map(ip=>({id:ip.id||undefined,ip_address:ip.ip_address,prefix_length:ip.prefix_length===''?null:Number(ip.prefix_length),purpose:ip.purpose||null}))}))};await get(api+`/devices/${deviceId}/interfaces`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
async function openInterfaceForm(id=''){
 const item=id?await get(api+`/resources/interfaces/${id}`):{};
 const devices=(await get(api+'/resources/devices?limit=1000')).items;
 await loadInterfaceCatalogs();
 const ips=id?(await get(api+`/resources/interface-ips?interface_id=${id}&limit=1000`)).items:[];
 interfaceRows=[{...item,ips}];
 document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+'Интерфейс';
 document.getElementById('formGrid').innerHTML=`<div class="interface-editor field full"><div class="interface-card-grid"><label class="field"><span>Физическое устройство *</span><select id="single-if-device" required><option value="">— выберите устройство —</option>${devices.map(x=>`<option value="${esc(x.id)}" ${x.id===item.physical_device_id?'selected':''}>${esc(lookupLabel('devices',x))}</option>`).join('')}</select></label></div><div id="single-interface-card" class="interface-cards"></div></div>`;document.getElementById('single-interface-card').innerHTML=interfaceCardHtml(interfaceRows[0],0);
 document.getElementById('modal').classList.add('show');
}
async function saveInterfaceForm(){
 syncInterfaceRows();
 const x=interfaceRows[0]||{};
 const deviceId=document.getElementById('single-if-device')?.value;
 if(!deviceId||!x.name?.trim()) return notify('Укажите физическое устройство и имя интерфейса.','error');
 const payload={physical_device_id:deviceId,name:x.name.trim(),interface_type_id:x.interface_type_id||null,mac_address:x.mac_address||null,speed_id:x.speed_id||null,is_management:!!x.is_management,description:x.description||null};
 try{
   const saved=await get(api+`/resources/interfaces${editingId?'/'+editingId:''}`,{method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
   const oldIps=editingId?(await get(api+`/resources/interface-ips?interface_id=${editingId}&limit=1000`)).items:[];
   for(const ip of oldIps) await get(api+`/resources/interface-ips/${ip.id}`,{method:'DELETE'});
   for(const ip of (x.ips||[]).filter(ip=>ip.ip_address?.trim())) await get(api+'/resources/interface-ips',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({interface_id:saved.id,ip_address:ip.ip_address.trim(),prefix_length:ip.prefix_length===''?null:Number(ip.prefix_length),purpose:ip.purpose||null,is_management:!!x.is_management})});
   closeModal(true);await renderList();
 }catch(e){notifyError(e)}
}
async function openQuickModal(target,sourceField,sourceIndex=null,parentState=null){if(!quickFields[target])return notify('Для этого справочника быстрое добавление не настроено.','error');quickTarget={resource:target,sourceField,sourceIndex};quickReturn=parentState||null;document.getElementById('quickModalTitle').textContent='Добавить: '+(quickLabels[target]||labels[sourceField]||target);let html=[];for(const [name,label,type,required] of quickFields[target]){if(type==='fk'){const map={building_id:'buildings',room_id:'rooms',device_type_id:'device-types',manufacturer_id:'manufacturers',category_id:'os-categories',parent_id:'departments'};const rr=map[name],opts=(await get(api+`/resources/${rr}?limit=1000`)).items;let selected='';if(target==='device-models'&&name==='manufacturer_id')selected=document.getElementById('field-manufacturer_id')?.value||'';if(target==='device-models'&&name==='device_type_id')selected=document.getElementById('field-device_type_id')?.value||'';if(target==='rooms'&&name==='building_id')selected=document.getElementById('field-building_id')?.value||'';if(target==='racks'&&name==='room_id')selected=document.getElementById('field-room_id')?.value||'';if(target==='departments'&&name==='parent_id')selected='';let addButton='';if(target==='device-models'&&name==='device_type_id'||target==='device-models'&&name==='manufacturer_id'){const childTarget=rr;const childSource=`device-models-${name}`;addButton=`<button type="button" class="btn gray inline-add" title="Добавить ${esc(label)}" onclick="openNestedDeviceCatalog('${childTarget}','${childSource}')">＋</button>`;}html.push(`<label class="field"><span>${label}${required?' *':''}</span><div class="lookup-row"><select name="${name}" ${required?'required':''}>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===selected?'selected':''}>${esc(lookupLabel(rr,o))}</option>`).join('')}</select>${addButton}</div></label>`);}else if(type==='textarea')html.push(`<label class="field full"><span>${label}</span><textarea name="${name}"></textarea></label>`);else html.push(`<label class="field"><span>${label}${required?' *':''}</span><input type="${type}" name="${name}" ${required?'required':''}></label>`);}document.getElementById('quickFormGrid').innerHTML=html.join('');if(parentState?.values){for(const [k,v] of Object.entries(parentState.values)){const el=document.querySelector(`#quickForm [name=\"${k}\"]`);if(el)el.value=v||'';}}document.getElementById('quickModal').classList.add('show');}
async function openNestedDeviceCatalog(target,sourceField){const parent={resource:'device-models',sourceField:'model_id',sourceIndex:null,values:Object.fromEntries(new FormData(document.getElementById('quickForm')).entries())};await openQuickModal(target,sourceField,null,parent);}
async function saveQuickForm(e){e.preventDefault();if(!quickTarget)return;const target={...quickTarget};let data={};for(const [k,v0] of new FormData(e.target).entries())data[k]=v0===''?null:v0;if(data.height_u!==null&&data.height_u!==undefined)data.height_u=Number(data.height_u);try{const created=await get(api+`/resources/${target.resource}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
if((target.resource==='device-types'||target.resource==='manufacturers')&&target.sourceField?.startsWith('device-models-')){const parent=quickReturn;quickReturn=null;closeQuickModal();if(parent){await openQuickModal(parent.resource,parent.sourceField,parent.sourceIndex,null);const f=document.querySelector(`#quickForm [name=\"${target.sourceField.endsWith('device_type_id')?'device_type_id':'manufacturer_id'}\"]`);if(f){const opt=document.createElement('option');opt.value=created.id;opt.textContent=lookupLabel(target.resource,created);f.appendChild(opt);f.value=created.id;}const vals=parent.values||{};for(const [k,v] of Object.entries(vals)){const el=document.querySelector(`#quickForm [name=\"${k}\"]`);if(el)el.value=v||'';}}return;}if(target.resource==='interface-speeds'||target.resource==='interface-types'){await loadInterfaceCatalogs();if(Number.isInteger(target.sourceIndex)&&interfaceRows[target.sourceIndex]){interfaceRows[target.sourceIndex][target.sourceField]=created.id;}closeQuickModal();renderInterfaceEditor();return;}
if(target.resource==='software-assets'&&target.sourceField?.startsWith('vm-software-')){
  window.currentSoftwareAssets=[...(window.currentSoftwareAssets||[]),created];
  const idx=Number(target.sourceField.slice('vm-software-'.length));
  syncVMSoftwareRows();
  if(vmSoftwareRows[idx])vmSoftwareRows[idx].software_asset_id=created.id;
  closeQuickModal();renderVMSoftwareRows();return;
}if(target.resource==='vlans'&&target.sourceField==='device-type-vlan'&&window.deviceTypeEditor){window.deviceTypeEditor.vlans.push(created);window.deviceTypeEditor.selected.add(created.id);const sel=document.getElementById('device-type-vlan');if(sel){const opt=document.createElement('option');opt.value=created.id;opt.textContent=(created.vlan_id+' — '+created.name);sel.appendChild(opt);sel.value=created.id;}renderDeviceTypeVlanList();closeQuickModal();return;}
if(target.resource==='vlans'&&target.sourceField==='device-vlan-new'){
   syncDeviceVlanRows();
   let row={vlan_id:created.id,ip_address:'',prefix_length:'',is_management:false,description:''};
   if(editingId){
     // Persist the link right away for an already-saved device: otherwise the VLAN itself gets
     // created in the catalog (a real, permanent side effect) but the link to this device only
     // lives in memory and is lost if the user cancels the form.
     try{const link=await get(api+'/resources/device-vlans',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({physical_device_id:editingId,vlan_id:created.id,ip_address:null,prefix_length:null,is_management:false,description:null})});row={...row,id:link.id};}catch(e){notifyError(e)}
   }
   deviceVlanRows.push(row);
   window.currentDeviceVlanOptions=[...(window.currentDeviceVlanOptions||[]),created];window.currentDeviceVlanAll=[...(window.currentDeviceVlanAll||[]),created];renderDeviceVlanRows();syncDeviceVlanOptionsFromRows();closeQuickModal();return;
 }
 if(target.resource==='embedded-os'&&target.sourceField==='embedded_os_id'){const f=document.getElementById('field-embedded_os_id');if(f){const opt=document.createElement('option');opt.value=created.id;opt.textContent=lookupLabel('embedded-os',created);f.appendChild(opt);f.value=created.id;}closeQuickModal();return;}
 if(target.resource==='connection-types'){const f=document.getElementById('conn-type');if(f){const opt=document.createElement('option');opt.value=created.id;opt.textContent=created.name||created.id;f.appendChild(opt);f.value=created.id;connectionState.connection_type_id=created.id;}closeQuickModal();return;}let field=document.getElementById('field-'+target.sourceField);
 if(target.resource==='device-models'&&target.sourceField==='model_id'){
   const modelField=document.getElementById('field-model_id');
   if(modelField){const opt=document.createElement('option');opt.value=created.id;opt.textContent=created.model||created.id;modelField.appendChild(opt);modelField.value=created.id;
     const mf=document.getElementById('field-manufacturer_id'),tf=document.getElementById('field-device_type_id'); if(mf){mf.value=created.manufacturer_id||'';} if(tf){tf.value=created.device_type_id||'';}
     modelField.dispatchEvent(new Event('change',{bubbles:true}));
   }
   closeQuickModal();return;
 }
 if(target.resource==='operating-systems'&&target.sourceField==='operating_system_id'){
   const osField=document.getElementById('field-operating_system_id');
   if(osField){const opt=document.createElement('option');opt.value=created.id;opt.textContent=lookupLabel('operating-systems',created);osField.appendChild(opt);osField.value=created.id;}
   const versionField=document.getElementById('field-os-version');if(versionField)versionField.value=created.version||'';
   closeQuickModal();return;
 }
 if(target.sourceField==='is-support-org'){ field=document.getElementById('is-support-org'); if(field){ const opt=document.createElement('option'); opt.value=created.id; opt.textContent=lookupLabel('support-organizations',created); field.appendChild(opt); field.value=created.id; } closeQuickModal(); return; }
 if(target.sourceField==='is-protocol-catalog') { if(Number.isInteger(target.sourceIndex)&&window.isEditor){window.isEditor.protocolCatalogs=window.isEditor.protocolCatalogs||[];window.isEditor.protocolCatalogs.push(created);window.isEditor.details.protocols[target.sourceIndex].protocol_catalog_id=created.id;window.isEditor.details.protocols[target.sourceIndex].protocol=created.protocol_type;window.isEditor.details.protocols[target.sourceIndex].port=created.port;renderISDetails();closeQuickModal();return;} }
 if(target.sourceField==='is-department'&&window.isEditor){window.isEditor.deps.push(created);window.isEditor.details.departments.push({department_id:created.id});renderISDetails();closeQuickModal();return;}
 if(target.sourceField==='is-support-method'&&window.isEditor){window.isEditor.supportMethods.push(created);renderISSupportMethodOptions();const sel=document.getElementById('is-support-method');if(sel)sel.value=created.id;closeQuickModal();return;}
 if(target.sourceField==='is-crypto-description'&&window.isEditor){window.isEditor.cryptoMeans.push(created);const sel=document.getElementById('is-crypto-description');if(sel){sel.innerHTML='<option value="">— не выбрано —</option>'+window.isEditor.cryptoMeans.map(o=>`<option value="${esc(o.id)}">${esc(o.name)}</option>`).join('');sel.value=created.id;}closeQuickModal();return;}
 if(target.sourceField==='is-placement-asset'&&window.isEditor){window.isEditor.placementAssetsCatalog.push(created);window.isEditor.details.placement_assets.push({placement_asset_id:created.id});renderISDetails();closeQuickModal();return;}
 if(field){const opt=document.createElement('option');opt.value=created.id;opt.textContent=lookupLabel(target.resource,created);field.appendChild(opt);field.value=created.id;field.dispatchEvent(new Event('change',{bubbles:true}));}
 closeQuickModal();}catch(err){notifyError(err)}}
function closeQuickModal(){document.getElementById('quickModal').classList.remove('show');quickTarget=null}
async function saveForm(e){e.preventDefault();if(resource==='device-types'){saveDeviceTypeForm();return;}if(resource==='connections'){await saveConnectionForm();return;}if(resource==='interfaces'){await saveInterfaceForm();return;}if(resource==='information-systems'){await saveInformationSystemForm();return;}if(resource==='vlans'){await saveVlanForm();return;}let data={};for(const [k,v0] of new FormData(e.target).entries()){let v=v0===''?null:v0,c=schema.columns.find(x=>x.name===k);if(c?.type==='BOOLEAN'&&v!==null)v=v==='true';if(c&&String(c.type).toUpperCase().includes('INTEGER')&&v!==null)v=Number(v);data[k]=v;}async function send(){return get(api+`/resources/${resource}${editingId?'/'+editingId:''}`,{method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});}try{let saved;for(let attempt=0;attempt<3;attempt++){try{saved=await send();break;}catch(err){const parsed=parseApiError(err);if(resource==='devices'&&parsed.code==='DUPLICATE_SYSTEM_NAME'&&confirm(parsed.message+'\n\nОК — сохранить дубликат.')){data.confirm_system_name_duplicate=true;continue;}if(resource==='devices'&&parsed.code==='RACK_POSITION_OCCUPIED'&&confirm(parsed.message)){data.confirm_rack_position_reassign=true;continue;}throw err;}}if(!saved)return;if(resource==='devices'){await saveDeviceVlans(saved.id);await saveDeviceInterfaces(saved.id);await saveDeviceOpenPorts(saved.id);}if(resource==='vms'){await saveVMIPs(saved.id);await saveVMOpenPorts(saved.id);await saveVMSoftware(saved.id);}closeModal(true);await renderList();}catch(err){notifyError(err)}}
// Предупреждение о потере несохранённых изменений — только для самых объёмных форм
// (устройство, ИС), где случайное закрытие теряет больше всего набранного текста и настроек.
// Для остальных типов записей captureFormSnapshot() намеренно возвращает null, и closeModal()
// ведёт себя как раньше — без диалога подтверждения.
let formOpenSnapshot = null;
function captureFormSnapshot() {
  if (resource === 'devices') {
    if (typeof syncInterfaceRows === 'function') syncInterfaceRows();
    if (typeof syncDeviceVlanRows === 'function') syncDeviceVlanRows();
    const fields = {};
    const form = document.getElementById('form');
    if (form) new FormData(form).forEach((v, k) => { fields[k] = v; });
    return JSON.stringify({ fields, interfaceRows, deviceVlanRows });
  }
  if (resource === 'information-systems' && window.isEditor) {
    syncISDetails();
    const fields = {};
    ['is-name','is-description','is-purpose','is-localization','is-support-org','is-support-method','is-process','is-crypto','is-crypto-description','is-siem'].forEach(id => {
      const el = document.getElementById(id);
      if (el) fields[id] = el.value;
    });
    return JSON.stringify({ fields, details: window.isEditor.details });
  }
  return null;
}
function markFormOpened() { formOpenSnapshot = captureFormSnapshot(); }
function hasUnsavedChanges() {
  if (formOpenSnapshot === null) return false;
  return captureFormSnapshot() !== formOpenSnapshot;
}
function closeModal(skipConfirm) {
  if (!skipConfirm && hasUnsavedChanges() && !confirm('Изменения не сохранены. Закрыть без сохранения?')) return;
  formOpenSnapshot = null;
  document.getElementById('modal').classList.remove('show');
}
// Дополняет closeModal(): предупреждает и при закрытии/перезагрузке всей вкладки браузера, а не
// только при закрытии модального окна средствами интерфейса. Срабатывает лишь пока модальное
// окно с отслеживаемой формой (устройство/ИС) действительно открыто и видимо на экране.
window.addEventListener('beforeunload', (e) => {
  const modalVisible = document.getElementById('modal')?.classList.contains('show');
  if (modalVisible && hasUnsavedChanges()) {
    e.preventDefault();
    e.returnValue = '';
  }
});
async function removeItem(id){if(!confirm('Удалить запись?'))return;try{await get(api+`/resources/${resource}/${id}`,{method:'DELETE'});if(resource==='vlans')await renderVlanDashboard();else await renderList()}catch(err){notifyError(err)}}
async function generateReport(){try{const x=await get(api+'/reports/inventory',{method:'POST'});window.location=x.download_url;}catch(e){notifyError(e)}}
showDashboard();
