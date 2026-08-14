// device-interfaces.js — редактор физических интерфейсов устройства (карточки портов, генерация
// по шаблону, массовое редактирование, IP-адреса интерфейса) и редактор VLAN устройства
// (deviceVlanEditor, привязка VLAN к устройству, создание/копирование доменов VLAN), плюс форма
// одиночного интерфейса (openInterfaceForm/saveInterfaceForm, ресурс 'interfaces').
//
// Пятый шаг разбиения app.js (см. docs/frontend-modularization.md, вариант C). Состояние
// (interfaceRows, interfaceSpeedOptions, interfaceTypeOptions, deviceVlanRows,
// deviceVlanOptions) объявлено в core.js — этот файл его использует, но не объявляет. Связь с
// остальным app.js — только вызовы по клику/из диспетчеров openForm()/saveForm()/saveQuickForm()
// (resource==='devices'|'interfaces', target.resource==='interface-speeds'|'interface-types'),
// ничего здесь не выполняется на верхнем уровне при загрузке страницы, кроме создания
// deviceVlanEditor через attachNestedListEditor() (из vm-editors.js — должен грузиться раньше).

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
