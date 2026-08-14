// connections.js — форма создания/редактирования физического подключения между двумя портами
// устройств (источник/приёмник, тип подключения, активность, описание).
//
// Четвёртый шаг разбиения app.js на несколько обычных <script> (см.
// docs/frontend-modularization.md, вариант C). Самодостаточный блок: единственная связь с
// остальным app.js — вызовы openConnectionForm()/saveConnectionForm() из диспетчеров
// openForm()/saveForm() по условию resource==='connections', ничего из этого файла не
// выполняется на верхнем уровне при загрузке страницы.

let connectionState={sourceDevice:'',destinationDevice:'',sourceInterface:'',destinationInterface:'',connection_type_id:'',purpose:'',is_active:true,description:''};
async function connectionInterfaces(deviceId,current=''){
 if(!deviceId)return [];
 const items=(await get(api+`/resources/interfaces?physical_device_id=${deviceId}&limit=1000`)).items;
 const connections=(await get(api+'/resources/connections?limit=1000')).items;
 const occupied=new Set();
 for(const c of connections){if(c.id===editingId||c.is_active===false)continue;if(c.source_interface_id)occupied.add(c.source_interface_id);if(c.destination_interface_id)occupied.add(c.destination_interface_id);}
 return items.filter(x=>!occupied.has(x.id)||x.id===current);
}
async function openConnectionForm(id=''){const item=id?await get(api+`/resources/connections/${id}`):{};const src=item.source_interface_id?await get(api+`/resources/interfaces/${item.source_interface_id}`):null;const dst=item.destination_interface_id?await get(api+`/resources/interfaces/${item.destination_interface_id}`):null;connectionState={sourceDevice:src?.physical_device_id||'',destinationDevice:dst?.physical_device_id||'',sourceInterface:item.source_interface_id||'',destinationInterface:item.destination_interface_id||'',connection_type_id:item.connection_type_id||'',purpose:item.purpose||'',is_active:item.is_active!==false,description:item.description||''};const devices=(await get(api+'/resources/devices?limit=1000')).items,types=(await get(api+'/resources/connection-types?limit=1000')).items;document.getElementById('modalTitle').textContent=(id?'Изменить: ':'Добавить: ')+'Подключение';document.getElementById('formGrid').innerHTML=`<label class="field"><span>Исходное устройство *</span><select id="conn-source-device" onchange="onConnectionDeviceChanged('source')"><option value="">— выберите устройство —</option>${devices.map(x=>`<option value="${esc(x.id)}" ${x.id===connectionState.sourceDevice?'selected':''}>${esc(lookupLabel('devices',x))}</option>`).join('')}</select></label><label class="field"><span>Исходный порт *</span><select id="conn-source-interface" onchange="connectionState.sourceInterface=this.value" required></select></label><label class="field"><span>Конечное устройство *</span><select id="conn-destination-device" onchange="onConnectionDeviceChanged('destination')"><option value="">— выберите устройство —</option>${devices.map(x=>`<option value="${esc(x.id)}" ${x.id===connectionState.destinationDevice?'selected':''}>${esc(lookupLabel('devices',x))}</option>`).join('')}</select></label><label class="field"><span>Конечный порт *</span><select id="conn-destination-interface" onchange="connectionState.destinationInterface=this.value" required></select></label><label class="field"><span>Тип подключения *</span><div class="lookup-row"><select id="conn-type" onchange="connectionState.connection_type_id=this.value" required><option value="">— выберите тип —</option>${types.map(x=>`<option value="${esc(x.id)}" ${x.id===connectionState.connection_type_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><button type="button" class="btn gray inline-add" onclick="openQuickModal('connection-types','connection_type_id')">＋</button></div></label><label class="field"><span>Активно</span><select id="conn-active"><option value="true" ${connectionState.is_active?'selected':''}>Да</option><option value="false" ${!connectionState.is_active?'selected':''}>Нет</option></select></label><label class="field full"><span>Описание</span><textarea id="conn-description">${esc(connectionState.description)}</textarea></label>`;document.getElementById('modal').classList.add('show');await onConnectionDeviceChanged('source',true);await onConnectionDeviceChanged('destination',true);}
async function onConnectionDeviceChanged(side,keep=false){
 const dev=document.getElementById(side==='source'?'conn-source-device':'conn-destination-device');
 const sel=document.getElementById(side==='source'?'conn-source-interface':'conn-destination-interface');
 if(!dev||!sel)return;
 const current=side==='source'?connectionState.sourceInterface:connectionState.destinationInterface;
 const items=await connectionInterfaces(dev.value);
 sel.innerHTML='<option value="">'+(dev.value?(items.length?'— выберите свободный порт —':'— свободных портов нет —'):'— выберите устройство —')+'</option>'+items.map(x=>`<option value="${esc(x.id)}" ${x.id===current?'selected':''}>${esc(lookupLabel('interfaces',x))}</option>`).join('');
 sel.disabled=!dev.value||!items.length;
 if(keep && current && items.some(x=>x.id===current)) sel.value=current;
 else {sel.value='';if(side==='source')connectionState.sourceInterface='';else connectionState.destinationInterface='';}
}
async function saveConnectionForm(){
 const sourceDevice=document.getElementById('conn-source-device')?.value||'';
 const destinationDevice=document.getElementById('conn-destination-device')?.value||'';
 const sourceInterface=document.getElementById('conn-source-interface')?.value||'';
 const destinationInterface=document.getElementById('conn-destination-interface')?.value||'';
 const connectionType=document.getElementById('conn-type')?.value||'';
 if(!sourceDevice||!sourceInterface)return notify('Выберите исходное устройство и его порт.','error');
 if(!destinationDevice||!destinationInterface)return notify('Выберите конечное устройство и его порт.','error');
 if(!connectionType)return notify('Выберите тип подключения.','error');
 connectionState={...connectionState,sourceDevice,destinationDevice,sourceInterface,destinationInterface,connection_type_id:connectionType,description:document.getElementById('conn-description').value||null,is_active:document.getElementById('conn-active').value==='true'};
 try{await get(api+`/resources/connections${editingId?'/'+editingId:''}`,{method:editingId?'PUT':'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_interface_id:sourceInterface,destination_interface_id:destinationInterface,connection_type_id:connectionType,purpose:connectionState.purpose,is_active:connectionState.is_active,description:connectionState.description})});closeModal(true);await renderList();}catch(e){notifyError(e)}
}
