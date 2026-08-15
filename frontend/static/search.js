// search.js — сквозной поиск (globalSearch): устройства, ИС, ВМ, интерфейсы, а также IP-адреса
// из шести разных таблиц (interface-ips/vm-ips/is-ips/is-sources/device-vlans/open-ports —
// каждая резолвится к своему владельцу для перехода по клику) — и рендер результатов.
//
// Девятый шаг разбиения app.js (см. docs/frontend-modularization.md, вариант C). Самодостаточный
// экран: единственная внешняя зависимость — общие утилиты get/api/esc/lookupLabel из core.js и
// openResource()/openForm() из app.js (переход к найденной записи). globalSearchResults — let,
// а не var: используется только внутри этого файла (в отличие от auditFilters/vlanBulkAssignOpen
// в audit-log.js/vlan.js, которые explicitly понадобились как var для доступа тестов через win.X,
// здесь такой необходимости нет — прямых тестов на globalSearch с проверкой состояния через win.X
// пока нет).

let globalSearchResults=[];
async function globalSearch(q){
 q=(q||'').trim();
 if(!q)return;
 const enc=encodeURIComponent(q);
 const safeList=async(url)=>{try{return (await get(url)).items;}catch(_){return [];}};
 const [devices,isys,vms,interfaces,ifaceIps,vmIps,isIps,isSources,deviceVlanIps,openPorts]=await Promise.all([
   safeList(api+`/resources/devices?q=${enc}&limit=15`),
   safeList(api+`/resources/information-systems?q=${enc}&limit=15`),
   safeList(api+`/resources/vms?q=${enc}&limit=15`),
   safeList(api+`/resources/interfaces?q=${enc}&limit=15`),
   safeList(api+`/resources/interface-ips?q=${enc}&limit=15`),
   safeList(api+`/resources/vm-ips?q=${enc}&limit=15`),
   safeList(api+`/resources/is-ips?q=${enc}&limit=15`),
   safeList(api+`/resources/is-sources?q=${enc}&limit=15`),
   safeList(api+`/resources/device-vlans?q=${enc}&limit=15`),
   safeList(api+`/resources/open-ports?q=${enc}&limit=15`),
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
 // Ниже — IP-адреса, хранящиеся не на самом интерфейсе/ВМ, а в связанных таблицах (внешнее
 // взаимодействие ИС, IP на VLAN устройства, IP открытого порта устройства/ВМ). Раньше сквозной
 // поиск их не находил вовсе — искать IP приходилось вручную по разделам.
 for(const ip of isIps){
   try{
     const is_=await get(api+`/resources/information-systems/${ip.information_system_id}`);
     results.push({section:'IP информационных систем',title:`${ip.ip_address} — ИС «${is_.name}»`,open:async()=>{await openResource('information-systems');await openForm(is_.id);}});
   }catch(_){}
 }
 for(const src of isSources){
   if(!src.ip_address)continue;
   try{
     const is_=await get(api+`/resources/information-systems/${src.information_system_id}`);
     results.push({section:'IP внешних источников ИС',title:`${src.ip_address} — источник ИС «${is_.name}»`,open:async()=>{await openResource('information-systems');await openForm(is_.id);}});
   }catch(_){}
 }
 for(const vlanIp of deviceVlanIps){
   if(!vlanIp.ip_address)continue;
   try{
     const dev=await get(api+`/resources/devices/${vlanIp.physical_device_id}`);
     results.push({section:'IP на VLAN устройства',title:`${vlanIp.ip_address} — ${lookupLabel('devices',dev)}`,open:async()=>{await openResource('devices');await openForm(dev.id);}});
   }catch(_){}
 }
 for(const port of openPorts){
   if(!port.ip_address)continue;
   try{
     const isDevice=port.owner_type==='physical_device';
     const owner=await get(api+`/resources/${isDevice?'devices':'vms'}/${port.owner_id}`);
     const ownerLabel=isDevice?lookupLabel('devices',owner):(owner.name||owner.id);
     results.push({section:'IP открытых портов',title:`${port.ip_address}:${port.port} — ${ownerLabel}`,open:async()=>{await openResource(isDevice?'devices':'vms');await openForm(owner.id);}});
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
