// app.js — маршрутизация, дашборд, универсальный список/форма ресурсов, формы ИС/устройства/
// подключения, интерфейсы и VLAN устройства, быстрое добавление в справочники, импорт CSV.
//
// Базовые утилиты без зависимостей вынесены в core.js, редакторы вложенных списков ВМ/устройства
// (VM IP/порты/ПО, открытые порты устройства) — в vm-editors.js. Оба подключаются раньше этого
// файла (см. index.html), поэтому их функции/константы доступны здесь напрямую.

async function showDashboard(){
 const d=await get(api+'/dashboard');
 const cards=[['information_systems','ИС','information-systems'],['physical_devices','Физические устройства','devices'],['virtual_machines','VM','vms'],['containers','Контейнеры','containers'],['connections','Подключения','connections'],['vlan','VLAN','vlans'],['software','ПО','software-assets']];
 content.innerHTML=`<div class="top"><h2>Dashboard</h2><div class="actions"><button class="btn gray" onclick="generateTestData(this)">Заполнить тестовыми данными</button><button class="btn gray" onclick="openResource('audit-log')">Аудит</button><button class="btn" onclick="generateReport(this)">Сформировать Excel</button></div></div><div class="cards">${cards.map(x=>`<button class="card" style="text-align:left;cursor:pointer" onclick="openResource('${x[2]}')"><span>${x[1]}</span><b>${d[x[0]]||0}</b><span class="muted">Открыть →</span></button>`).join('')}</div>`;
}
async function openResource(r){resource=r;if(r==='vlans'){await renderVlanDashboard();return;}if(r==='audit-log'){await renderAuditLog();return;}schema=await get(api+`/resources/${r}/schema`);await renderList()}
async function generateTestData(btn){if(!confirm('Добавить демонстрационные тестовые данные? Существующие данные не будут удалены.'))return;await withBusyButton(btn,async()=>{try{const r=await get(api+'/seed/test',{method:'POST'});notify(r.message+`\nИдентификатор набора: ${r.tag}`,'success');await showDashboard();}catch(e){notifyError(e)}});}
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
   return `<th class="sortable-th" onclick="sortListBy('${c.name}')">${esc(fieldLabel(c))}${arrow}</th>`;
 }).join('')+'<th>Действия</th>';
 body.innerHTML=rows.map(x=>`<tr>${listCols.map(c=>`<td>${esc(listCell(x,c))}</td>`).join('')}<td><button class="btn gray" onclick="openForm('${x.id}')">Изменить</button> ${resource==='vlan-domains'&&x.source_device_id?`<button class="btn gray" onclick="syncVlanDomain('${x.id}',this)">Синхронизировать</button> `:''}<button class="btn red" onclick="removeItem('${x.id}')">Удалить</button></td></tr>`).join('');
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
// Разрешение подписи поля по имени колонки — обычно из общего labels{}, но 'parent_id' встречается
// у двух разных иерархических справочников (departments/structural-units) с разным смыслом
// "родителя"; общий словарь не умеет различать по ресурсу, поэтому такие поля разрешаются здесь
// с учётом текущего resource, а не только по имени колонки.
function fieldLabel(c){
 if(resource==='structural-units'&&c.name==='parent_id')return 'Родительская структурная единица';
 return labels[c.name]||c.name;
}
async function fieldHtml(c,v,item={}){
 const label=fieldLabel(c);
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
     const canQuick=['buildings','rooms','racks','device-types','manufacturers','device-models','os-categories','operating-systems','interface-types','interface-speeds','connection-types','structural-units'].includes(rr);
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
async function openQuickModal(target,sourceField,sourceIndex=null,parentState=null){if(!quickFields[target])return notify('Для этого справочника быстрое добавление не настроено.','error');quickTarget={resource:target,sourceField,sourceIndex};quickReturn=parentState||null;document.getElementById('quickModalTitle').textContent='Добавить: '+(quickLabels[target]||labels[sourceField]||target);let html=[];for(const [name,label,type,required] of quickFields[target]){if(type==='fk'){const map={building_id:'buildings',room_id:'rooms',device_type_id:'device-types',manufacturer_id:'manufacturers',category_id:'os-categories',parent_id:target==='structural-units'?'structural-units':'departments',structural_unit_id:'structural-units'};const rr=map[name],opts=(await get(api+`/resources/${rr}?limit=1000`)).items;let selected='';if(target==='device-models'&&name==='manufacturer_id')selected=document.getElementById('field-manufacturer_id')?.value||'';if(target==='device-models'&&name==='device_type_id')selected=document.getElementById('field-device_type_id')?.value||'';if(target==='rooms'&&name==='building_id')selected=document.getElementById('field-building_id')?.value||'';if(target==='racks'&&name==='room_id')selected=document.getElementById('field-room_id')?.value||'';if(target==='departments'&&name==='parent_id')selected='';let addButton='';if(target==='device-models'&&name==='device_type_id'||target==='device-models'&&name==='manufacturer_id'){const childTarget=rr;const childSource=`device-models-${name}`;addButton=`<button type="button" class="btn gray inline-add" title="Добавить ${esc(label)}" onclick="openNestedDeviceCatalog('${childTarget}','${childSource}')">＋</button>`;}html.push(`<label class="field"><span>${label}${required?' *':''}</span><div class="lookup-row"><select name="${name}" ${required?'required':''}>${opts.map(o=>`<option value="${esc(o.id)}" ${o.id===selected?'selected':''}>${esc(lookupLabel(rr,o))}</option>`).join('')}</select>${addButton}</div></label>`);}else if(type==='textarea')html.push(`<label class="field full"><span>${label}</span><textarea name="${name}"></textarea></label>`);else html.push(`<label class="field"><span>${label}${required?' *':''}</span><input type="${type}" name="${name}" ${required?'required':''}></label>`);}document.getElementById('quickFormGrid').innerHTML=html.join('');if(parentState?.values){for(const [k,v] of Object.entries(parentState.values)){const el=document.querySelector(`#quickForm [name=\"${k}\"]`);if(el)el.value=v||'';}}document.getElementById('quickModal').classList.add('show');}
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

// ---------- Выбор структурных единиц при генерации отчёта ----------
// Используется и дашбордом (регламентированный отчёт, generateReport) и конструктором
// (report_builder.js: rbGenerateTemplate) — единая точка, чтобы оба места вели себя одинаково.
// Возвращает Promise, разрешающийся в:
//   null      — без ограничения (полный отчёт, как без этой функции вообще);
//   string[]  — id выбранных структурных единиц (генерация ограничивается их оборудованием);
//   undefined — пользователь отменил формирование отчёта целиком.
// Если в базе нет ни одной структурной единицы, модалка не имеет смысла — сразу возвращает null,
// без лишнего шага для пользователей, которые эту функциональность не используют.
let _suModalResolve=null,_suModalUnits=[];
async function openStructuralUnitsModal(){
 const units=(await get(api+'/resources/structural-units?limit=1000')).items;
 if(!units.length)return null;
 return new Promise(resolve=>{
  _suModalResolve=resolve;_suModalUnits=units;
  _renderStructuralUnitsModal();
  document.getElementById('structuralUnitsModal').classList.add('show');
 });
}
function _renderStructuralUnitsModal(){
 const childrenOf={};
 _suModalUnits.forEach(u=>{const key=u.parent_id||'';(childrenOf[key]=childrenOf[key]||[]).push(u);});
 const ordered=[];
 (function walk(parentKey,depth){
  (childrenOf[parentKey]||[]).forEach(u=>{ordered.push({u,depth});walk(u.id,depth+1);});
 })('',0);
 document.getElementById('structuralUnitsBody').innerHTML=`
  <p class="muted">По умолчанию отчёт включает всё оборудование. Чтобы ограничить его конкретными структурными единицами, переключитесь на выбор ниже — выбор родительской единицы автоматически включает вложенные в неё.</p>
  <label class="su-radio-option"><input type="radio" name="su-mode" value="all" checked onchange="_suToggleMode()"> Всё оборудование (без ограничения)</label>
  <label class="su-radio-option"><input type="radio" name="su-mode" value="select" onchange="_suToggleMode()"> Выбрать структурные единицы</label>
  <div id="suUnitList" class="su-unit-list" style="display:none">
   <div style="margin-bottom:8px"><button type="button" class="btn gray" onclick="_suSetAll(true)">Отметить все</button> <button type="button" class="btn gray" onclick="_suSetAll(false)">Снять все</button></div>
   ${ordered.map(({u,depth})=>`<label style="padding-left:${depth*20}px"><input type="checkbox" class="su-checkbox" value="${esc(u.id)}"> ${esc(u.name)}</label>`).join('')}
  </div>`;
}
function _suToggleMode(){
 const mode=document.querySelector('input[name="su-mode"]:checked')?.value;
 document.getElementById('suUnitList').style.display=mode==='select'?'':'none';
}
function _suSetAll(checked){document.querySelectorAll('.su-checkbox').forEach(cb=>cb.checked=checked)}
function closeStructuralUnitsModal(){
 document.getElementById('structuralUnitsModal').classList.remove('show');
 const resolve=_suModalResolve;_suModalResolve=null;
 if(resolve)resolve(undefined);
}
function confirmStructuralUnitsModal(){
 const mode=document.querySelector('input[name="su-mode"]:checked')?.value;
 let ids=null;
 if(mode==='select'){
  ids=[...document.querySelectorAll('.su-checkbox:checked')].map(cb=>cb.value);
  if(!ids.length){notify('Отметьте хотя бы одну структурную единицу или выберите «Всё оборудование».','error');return;}
 }
 document.getElementById('structuralUnitsModal').classList.remove('show');
 const resolve=_suModalResolve;_suModalResolve=null;
 if(resolve)resolve(ids);
}

async function generateReport(btn){
 const structural_unit_ids=await openStructuralUnitsModal();
 if(structural_unit_ids===undefined)return; // отменено пользователем
 await withBusyButton(btn,async()=>{try{const x=await get(api+'/reports/inventory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({structural_unit_ids})});window.location=x.download_url;}catch(e){notifyError(e)}});
}

showDashboard();
