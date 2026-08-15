// vlan.js — всё, что касается VLAN на фронтенде: экран «VLAN» (дашборд + массовое назначение),
// форма отдельного VLAN, форма типа устройства (управляет разрешёнными для типа VLAN) и запуск
// синхронизации VLAN-домена.
//
// Восьмой шаг разбиения app.js (см. docs/frontend-modularization.md, вариант C). В отличие от
// предыдущих шагов, здесь собраны в один файл функции из ТРЁХ разных мест исходного app.js —
// это оправдано, поскольку разделение по расположению в файле уже не отражало разделение по
// смыслу: экран VLAN, форма VLAN и управление VLAN типа устройства — одна предметная область,
// которую пользователь воспринимает как единое целое. vlanBulkAssignOpen — var, а не let, по
// той же причине, что и auditFilters в audit-log.js (see История коммита 2219cd5).

let vlanBulkAssignOpen=false;
async function renderVlanDashboard(){
 const [data,devices]=await Promise.all([
   get(api+'/vlan-dashboard'),
   get(api+'/resources/devices?limit=1000').then(r=>r.items),
 ]);
 const allVlans=data.items.flatMap(g=>g.definitions);
 document.getElementById('content').innerHTML=`<div class="top"><div><h2>VLAN</h2><div class="muted">Одинаковый VLAN ID может иметь разные названия и описания на разных устройствах</div></div><div><button class="btn" onclick="openForm()">+ VLAN</button><button class="btn gray" onclick="toggleVlanBulkAssign()">${vlanBulkAssignOpen?'Скрыть массовое назначение':'Массовое назначение VLAN'}</button><button class="btn gray" onclick="openResource('vlan-domains')">Домены VLAN</button><button class="btn gray" onclick="showDashboard()">Dashboard</button></div></div><div class="panel">${vlanBulkAssignOpen?vlanBulkAssignPanelHtml(allVlans,devices):''}<div class="tablewrap"><table><thead><tr><th>VLAN ID</th><th>Название / описание</th><th>Домен</th><th>Устройства</th><th>IP / управление</th><th>Действия</th></tr></thead><tbody>${data.items.map(g=>g.definitions.map((v,j)=>`<tr>${j===0?`<td rowspan="${g.definitions.length}"><b>${esc(g.vlan_id)}</b></td>`:''}<td><b>${esc(v.name)}</b><br><span class="muted">${esc(v.description||'')}</span></td><td>${esc(v.domain_name)}</td><td>${esc(v.devices.map(d=>d.device_name).join(', ')||'—')}</td><td>${esc(v.devices.map(d=>d.ip_address?d.ip_address+(d.is_management?' (управление)':''):'не назначен').join(', ')||'—')}</td><td><button class="btn gray" onclick="openForm('${v.id}')">Изменить</button> <button class="btn red" onclick="removeItem('${v.id}')">Удалить</button></td></tr>`).join('')).join('')}</tbody></table></div></div>`;
}

// Разовое назначение одного VLAN сразу нескольким устройствам — в отличие от доменов VLAN
// (которые синхронизируют весь набор VLAN с "устройства-источника" и рассчитаны на повторное
// использование), это одноразовое действие без создания домена. IP-адрес намеренно не
// запрашивается: один и тот же IP на нескольких устройствах в одном VLAN был бы некорректен, а
// задание разных IP для каждого устройства сразу — это уже не массовое действие.
function vlanBulkAssignPanelHtml(allVlans,devices){
 return `<div class="bulk-edit-bar" style="flex-direction:column;align-items:stretch;gap:10px;margin-bottom:14px">
   <div style="display:flex;gap:16px;flex-wrap:wrap;align-items:end">
     <label class="field"><span class="if-select-label">VLAN</span><select id="vlan-bulk-vlan"><option value="">— выберите VLAN —</option>${allVlans.map(v=>`<option value="${esc(v.id)}">${esc(v.vlan_id+' — '+v.name+(v.domain_name?' ('+v.domain_name+')':''))}</option>`).join('')}</select></label>
     <label class="field"><span class="if-select-label">Описание (опционально)</span><input id="vlan-bulk-description" placeholder="Например: доступ для мониторинга"></label>
   </div>
   <div class="vlan-checks" style="max-height:220px;overflow:auto">
     <label><input type="checkbox" onchange="toggleAllVlanBulkDevices(this.checked)"> Выбрать все (${devices.length})</label>
     ${devices.map(d=>`<label><input type="checkbox" class="vlan-bulk-device" value="${esc(d.id)}"> ${esc(lookupLabel('devices',d))}</label>`).join('')||'<span class="muted">Устройств нет</span>'}
   </div>
   <div><button class="btn" onclick="applyVlanBulkAssign(this)">Назначить выбранным</button></div>
 </div>`;
}
function toggleVlanBulkAssign(){vlanBulkAssignOpen=!vlanBulkAssignOpen;renderVlanDashboard();}
function toggleAllVlanBulkDevices(checked){document.querySelectorAll('.vlan-bulk-device').forEach(el=>el.checked=checked);}
async function applyVlanBulkAssign(btn){
 const vlanId=document.getElementById('vlan-bulk-vlan').value;
 const deviceIds=Array.from(document.querySelectorAll('.vlan-bulk-device:checked')).map(el=>el.value);
 const description=document.getElementById('vlan-bulk-description').value||null;
 if(!vlanId){notify('Выберите VLAN','error');return;}
 if(!deviceIds.length){notify('Выберите хотя бы одно устройство','error');return;}
 await withBusyButton(btn,async()=>{
   try{
     const r=await get(api+'/device-vlans/bulk-assign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({physical_device_ids:deviceIds,vlan_id:vlanId,description})});
     notify(`Назначено: ${r.assigned}${r.skipped_existing?`, уже было назначено ранее: ${r.skipped_existing}`:''}`,'success');
     vlanBulkAssignOpen=false;
     await renderVlanDashboard();
   }catch(e){notifyError(e)}
 });
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

// Синхронизирует VLAN-домен: копирует VLAN исходного устройства на все остальные устройства
// домена (см. POST /api/v1/vlan-domains/{id}/sync на бэкенде). До этой кнопки эндпоинт был
// реализован и покрыт тестами, но не вызывался из интерфейса ни в одном месте.
async function syncVlanDomain(id,btn){
  await withBusyButton(btn,async()=>{
    try{
      const r=await get(api+`/vlan-domains/${id}/sync`,{method:'POST'});
      notify(`VLAN-домен синхронизирован: новых определений — ${r.created_definitions}, назначений — ${r.assigned}`,'success');
    }catch(e){notifyError(e)}
  });
}
