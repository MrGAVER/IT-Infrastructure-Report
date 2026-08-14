// vm-editors.js — общая фабрика редактора вложенных списков (attachNestedListEditor) и все
// редакторы на её основе для ВМ и устройств: IP-адреса ВМ, открытые порты ВМ, открытые порты
// физического устройства, программные активы ВМ.
//
// Второй шаг разбиения app.js на несколько обычных <script> (см. docs/frontend-modularization.md,
// вариант C). Выбрано как следующий кандидат после core.js, потому что это цельный,
// самодостаточный блок: единственная связь с остальным app.js — глобальные переменные состояния
// (vmIpRows, vmOpenPortRows, deviceOpenPortRows, vmSoftwareRows, объявленные в core.js) и вызовы
// load*/save* из форм устройства/ВМ в app.js, а сам блок ничего не вызывает из кода app.js.
//
// ВАЖНО: подключается раньше app.js (см. index.html) — app.js на верхнем уровне создаёт
// deviceVlanEditor через attachNestedListEditor(...) в момент разбора файла, а не по клику.

function attachNestedListEditor(stateGetter, {htmlAttr, rowHtml, emptyRow, emptyMessage, listId, sortRows, onAfterRemove}) {
  function orderedRows() {
    const rows = stateGetter();
    return sortRows ? sortRows(rows) : rows.map((x, i) => [x, i]);
  }
  function sync() {
    document.querySelectorAll(`[data-${htmlAttr}]`).forEach(el => {
      const rows = stateGetter();
      const i = +el.dataset[htmlAttr], k = el.dataset.k;
      if (!rows[i]) return;
      rows[i][k] = (el.type === 'checkbox' || el.type === 'radio') ? el.checked : el.value;
    });
  }
  function render() {
    const box = document.getElementById(listId);
    if (box) box.innerHTML = orderedRows().map(([x, i]) => rowHtml(x, i)).join('') || `<div class="muted">${emptyMessage}</div>`;
  }
  function add() { if (!emptyRow) return; sync(); stateGetter().push(emptyRow()); render(); }
  async function remove(i) {
    sync();
    const rows = stateGetter();
    const removed = rows[i];
    rows.splice(i, 1);
    render();
    if (onAfterRemove) await onAfterRemove(removed);
  }
  return { sync, render, add, remove };
}

function vmIpRowHtml(x,i){
 return `<div class="nested-row vm-ip-row"><input data-vmip="${i}" data-k="ip_address" placeholder="IP-адрес" value="${esc(x.ip_address||'')}"><input data-vmip="${i}" data-k="prefix_length" type="number" min="0" max="128" placeholder="Префикс" value="${esc(x.prefix_length??'')}"><input data-vmip="${i}" data-k="purpose" placeholder="Назначение" value="${esc(x.purpose||'')}"><label class="vm-ip-admin-label"><input type="checkbox" data-vmip="${i}" data-k="is_management" ${x.is_management?'checked':''}> IP администрирования</label><button type="button" class="btn red" onclick="removeVMIPRow(${i})">Удалить</button></div>`;
}
const vmIpEditor=attachNestedListEditor(()=>vmIpRows,{htmlAttr:'vmip',rowHtml:vmIpRowHtml,emptyRow:()=>({ip_address:'',prefix_length:'',purpose:'',is_management:false}),emptyMessage:'IP-адреса не добавлены',listId:'vm-ip-list'});
async function loadVMIPEditor(vmId){
 const box=document.getElementById('vmIpEditor');if(!box)return;
 vmIpRows=vmId?(await get(api+`/resources/vm-ips?virtual_machine_id=${vmId}&limit=1000`)).items:[];
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>IP-адреса виртуальной машины</b><span class="muted">Отметьте галочкой один или несколько IP как «IP администрирования» — они используются в отчете по информационным системам.</span></div><div id="vm-ip-list" class="nested-list">${vmIpRows.map((x,i)=>vmIpRowHtml(x,i)).join('')||'<div class="muted">IP-адреса не добавлены</div>'}</div><button type="button" class="btn gray" onclick="addVMIPRow()">+ IP-адрес</button></div>`;
}
function syncVMIPRows(){vmIpEditor.sync();}
function addVMIPRow(){vmIpEditor.add();}
function removeVMIPRow(i){vmIpEditor.remove(i);}
async function saveVMIPs(vmId){
 syncVMIPRows();
 const old=(await get(api+`/resources/vm-ips?virtual_machine_id=${vmId}&limit=1000`)).items;
 for(const x of old)await get(api+`/resources/vm-ips/${x.id}`,{method:'DELETE'});
 for(const x of vmIpRows){
   if(!x.ip_address?.trim())continue;
   await get(api+'/resources/vm-ips',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({virtual_machine_id:vmId,ip_address:x.ip_address.trim(),prefix_length:x.prefix_length===''||x.prefix_length==null?null:Number(x.prefix_length),purpose:x.purpose||null,is_management:!!x.is_management})});
 }
}
function vmOpenPortRowHtml(x,i){
 const cat=window.currentProtocolCatalog||[];
 const transport=x.transport_protocol||'TCP';
 return `<div class="nested-row vm-openport-row"><select data-vmop="${i}" data-k="protocol_catalog_id" onchange="onVMOpenPortCatalogChanged(${i})"><option value="">— справочник —</option>${cat.map(o=>`<option value="${esc(o.id)}" ${o.id===x.protocol_catalog_id?'selected':''}>${esc(`${o.port} / ${o.protocol_type}`)}</option>`).join('')}</select><input data-vmop="${i}" data-k="port" type="number" min="1" max="65535" placeholder="Порт" value="${esc(x.port??'')}"><input data-vmop="${i}" data-k="protocol" placeholder="Протокол" value="${esc(x.protocol||'')}"><select data-vmop="${i}" data-k="transport_protocol"><option value="TCP" ${transport==='TCP'?'selected':''}>TCP</option><option value="UDP" ${transport==='UDP'?'selected':''}>UDP</option><option value="TCP/UDP" ${transport==='TCP/UDP'?'selected':''}>TCP/UDP</option></select><input data-vmop="${i}" data-k="description" placeholder="Описание" value="${esc(x.description||'')}"><button type="button" class="btn red" onclick="removeVMOpenPortRow(${i})">Удалить</button></div>`;
}
const vmOpenPortsEditor=attachNestedListEditor(()=>vmOpenPortRows,{htmlAttr:'vmop',rowHtml:vmOpenPortRowHtml,emptyRow:()=>({protocol_catalog_id:'',port:'',protocol:'',transport_protocol:'TCP',description:''}),emptyMessage:'Открытые порты не добавлены',listId:'vm-openport-list'});
async function loadVMOpenPortsEditor(vmId){
 const box=document.getElementById('vmOpenPortsEditor');if(!box)return;
 vmOpenPortRows=vmId?(await get(api+`/resources/open-ports?owner_type=virtual_machine&owner_id=${vmId}&limit=1000`)).items:[];
 window.currentProtocolCatalog=(await get(api+'/resources/protocol-port-catalog?limit=1000')).items;
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>Открытые порты / протоколы</b><span class="muted">Используются при заполнении соответствующего поля в отчете по информационным системам.</span></div><div id="vm-openport-list" class="nested-list">${vmOpenPortRows.map((x,i)=>vmOpenPortRowHtml(x,i)).join('')||'<div class="muted">Открытые порты не добавлены</div>'}</div><button type="button" class="btn gray" onclick="addVMOpenPortRow()">+ Открытый порт</button></div>`;
}
function syncVMOpenPortRows(){vmOpenPortsEditor.sync();}
function renderVMOpenPortRows(){vmOpenPortsEditor.render();}
function addVMOpenPortRow(){vmOpenPortsEditor.add();}
function removeVMOpenPortRow(i){vmOpenPortsEditor.remove(i);}
function onVMOpenPortCatalogChanged(i){syncVMOpenPortRows();const cat=(window.currentProtocolCatalog||[]).find(o=>o.id===vmOpenPortRows[i].protocol_catalog_id);if(cat){vmOpenPortRows[i].port=cat.port;vmOpenPortRows[i].protocol=cat.protocol_type;}renderVMOpenPortRows();}
async function saveVMOpenPorts(vmId){
 syncVMOpenPortRows();
 const old=(await get(api+`/resources/open-ports?owner_type=virtual_machine&owner_id=${vmId}&limit=1000`)).items;
 for(const x of old)await get(api+`/resources/open-ports/${x.id}`,{method:'DELETE'});
 for(const x of vmOpenPortRows){
   if(!x.port&&!x.protocol_catalog_id)continue;
   await get(api+'/resources/open-ports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner_type:'virtual_machine',owner_id:vmId,protocol_catalog_id:x.protocol_catalog_id||null,port:x.port?Number(x.port):null,protocol:x.protocol||null,transport_protocol:x.transport_protocol||'TCP',description:x.description||null})});
 }
}
function deviceOpenPortRowHtml(x,i){
 const cat=window.currentProtocolCatalog||[];
 const transport=x.transport_protocol||'TCP';
 return `<div class="nested-row vm-openport-row"><select data-devop="${i}" data-k="protocol_catalog_id" onchange="onDeviceOpenPortCatalogChanged(${i})"><option value="">— справочник —</option>${cat.map(o=>`<option value="${esc(o.id)}" ${o.id===x.protocol_catalog_id?'selected':''}>${esc(`${o.port} / ${o.protocol_type}`)}</option>`).join('')}</select><input data-devop="${i}" data-k="port" type="number" min="1" max="65535" placeholder="Порт" value="${esc(x.port??'')}"><input data-devop="${i}" data-k="protocol" placeholder="Протокол" value="${esc(x.protocol||'')}"><select data-devop="${i}" data-k="transport_protocol"><option value="TCP" ${transport==='TCP'?'selected':''}>TCP</option><option value="UDP" ${transport==='UDP'?'selected':''}>UDP</option><option value="TCP/UDP" ${transport==='TCP/UDP'?'selected':''}>TCP/UDP</option></select><input data-devop="${i}" data-k="description" placeholder="Описание" value="${esc(x.description||'')}"><button type="button" class="btn red" onclick="removeDeviceOpenPortRow(${i})">Удалить</button></div>`;
}
const deviceOpenPortsEditor=attachNestedListEditor(()=>deviceOpenPortRows,{htmlAttr:'devop',rowHtml:deviceOpenPortRowHtml,emptyRow:()=>({protocol_catalog_id:'',port:'',protocol:'',transport_protocol:'TCP',description:''}),emptyMessage:'Открытые порты не добавлены',listId:'device-openport-list'});
async function loadDeviceOpenPortsEditor(deviceId){
 const box=document.getElementById('deviceOpenPortsEditor');if(!box)return;
 deviceOpenPortRows=deviceId?(await get(api+`/resources/open-ports?owner_type=physical_device&owner_id=${deviceId}&limit=1000`)).items:[];
 window.currentProtocolCatalog=window.currentProtocolCatalog||(await get(api+'/resources/protocol-port-catalog?limit=1000')).items;
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>Открытые порты / протоколы устройства</b><span class="muted">Используются в отчете на листе "Организация подключений" (перечень открытых портов и протокол/технология).</span></div><div id="device-openport-list" class="nested-list">${deviceOpenPortRows.map((x,i)=>deviceOpenPortRowHtml(x,i)).join('')||'<div class="muted">Открытые порты не добавлены</div>'}</div><button type="button" class="btn gray" onclick="addDeviceOpenPortRow()">+ Открытый порт</button></div>`;
}
function syncDeviceOpenPortRows(){deviceOpenPortsEditor.sync();}
function renderDeviceOpenPortRows(){deviceOpenPortsEditor.render();}
function addDeviceOpenPortRow(){deviceOpenPortsEditor.add();}
function removeDeviceOpenPortRow(i){deviceOpenPortsEditor.remove(i);}
function onDeviceOpenPortCatalogChanged(i){syncDeviceOpenPortRows();const cat=(window.currentProtocolCatalog||[]).find(o=>o.id===deviceOpenPortRows[i].protocol_catalog_id);if(cat){deviceOpenPortRows[i].port=cat.port;deviceOpenPortRows[i].protocol=cat.protocol_type;}renderDeviceOpenPortRows();}
async function saveDeviceOpenPorts(deviceId){
 syncDeviceOpenPortRows();
 const old=(await get(api+`/resources/open-ports?owner_type=physical_device&owner_id=${deviceId}&limit=1000`)).items;
 for(const x of old)await get(api+`/resources/open-ports/${x.id}`,{method:'DELETE'});
 for(const x of deviceOpenPortRows){
   if(!x.port&&!x.protocol_catalog_id)continue;
   await get(api+'/resources/open-ports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({owner_type:'physical_device',owner_id:deviceId,protocol_catalog_id:x.protocol_catalog_id||null,port:x.port?Number(x.port):null,protocol:x.protocol||null,transport_protocol:x.transport_protocol||'TCP',description:x.description||null})});
 }
}
function vmSoftwareRowHtml(x,i){
 const cat=window.currentSoftwareAssets||[];
 return `<div class="nested-row vm-software-row"><select data-vmsw="${i}" data-k="software_asset_id"><option value="">— выберите ПО —</option>${cat.map(o=>`<option value="${esc(o.id)}" ${o.id===x.software_asset_id?'selected':''}>${esc(o.name)}</option>`).join('')}</select><input data-vmsw="${i}" data-k="version" placeholder="Версия" value="${esc(x.version||'')}"><button type="button" class="btn gray inline-add" onclick="openQuickModal('software-assets','vm-software-'+${i})">＋</button><button type="button" class="btn red" onclick="removeVMSoftwareRow(${i})">Удалить</button></div>`;
}
const vmSoftwareEditor=attachNestedListEditor(()=>vmSoftwareRows,{htmlAttr:'vmsw',rowHtml:vmSoftwareRowHtml,emptyRow:()=>({software_asset_id:'',version:''}),emptyMessage:'Программные активы не добавлены',listId:'vm-software-list'});
async function loadVMSoftwareEditor(vmId){
 const box=document.getElementById('vmSoftwareEditor');if(!box)return;
 vmSoftwareRows=vmId?(await get(api+`/resources/vm-software?virtual_machine_id=${vmId}&limit=1000`)).items:[];
 window.currentSoftwareAssets=(await get(api+'/resources/software-assets?limit=1000')).items;
 box.innerHTML=`<div class="interface-editor"><div class="ie-head"><b>Развёрнутые программные активы</b><span class="muted">1С, Web-сервер, файловый, AD и т.п. — используется в отчете на листе "Организация управления ВМ".</span></div><div id="vm-software-list" class="nested-list">${vmSoftwareRows.map((x,i)=>vmSoftwareRowHtml(x,i)).join('')||'<div class="muted">Программные активы не добавлены</div>'}</div><button type="button" class="btn gray" onclick="addVMSoftwareRow()">+ Программный актив</button></div>`;
}
function syncVMSoftwareRows(){vmSoftwareEditor.sync();}
function renderVMSoftwareRows(){vmSoftwareEditor.render();}
function addVMSoftwareRow(){vmSoftwareEditor.add();}
function removeVMSoftwareRow(i){vmSoftwareEditor.remove(i);}
async function saveVMSoftware(vmId){
 syncVMSoftwareRows();
 const old=(await get(api+`/resources/vm-software?virtual_machine_id=${vmId}&limit=1000`)).items;
 for(const x of old)await get(api+`/resources/vm-software/${x.id}`,{method:'DELETE'});
 for(const x of vmSoftwareRows){
   if(!x.software_asset_id)continue;
   await get(api+'/resources/vm-software',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({virtual_machine_id:vmId,software_asset_id:x.software_asset_id,version:x.version||null})});
 }
}
