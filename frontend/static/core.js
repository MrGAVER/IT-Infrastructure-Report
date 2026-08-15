// core.js — базовая инфраструктура без внешних зависимостей: константы (справочники меток,
// список кешируемых ресурсов), кеш GET-запросов, единый разбор ошибок API, toast-уведомления,
// обёртка над fetch(), и мелкие форматирующие утилиты (esc/formatValue/lookupLabel).
//
// Первый шаг разбиения app.js на несколько обычных <script> (см.
// docs/frontend-modularization.md, вариант C): загружается раньше app.js/report_builder.js
// (см. порядок <script> в index.html), в глобальной области видимости — без type="module",
// поэтому объявленные здесь функции/константы доступны из остальных файлов так же, как раньше
// были доступны внутри одного app.js. Инлайн-обработчики onclick=/onchange= в HTML продолжают
// работать без изменений.
//
// Вынесено сюда, потому что ничего в этом файле не вызывает функции, объявленные ниже по коду
// app.js — это единственная часть исходного файла с нулевыми "исходящими" зависимостями, что
// делает её самым безопасным кандидатом для первого шага разбиения.

const api='/api/v1';
let resource=null,schema=null,editingId=null,rows=[],listCols=[],listLookups={},listSortColumn=null,listSortDirection=1;
let quickTarget=null,interfaceRows=[],interfaceSpeedOptions=[],interfaceTypeOptions=[],deviceVlanOptions=[],deviceVlanRows=[],vmIpRows=[],vmOpenPortRows=[],deviceOpenPortRows=[],vmSoftwareRows=[];
const quickLabels={'support-organizations':'Организация технической поддержки',organizations:'Организация',departments:'Подразделение',buildings:'Здание',rooms:'Помещение',racks:'Стойка','device-types':'Тип устройства',manufacturers:'Производитель','device-models':'Каталог оборудования (Производитель → Тип → Модель)','os-categories':'Категория ОС','operating-systems':'ОС','interface-types':'Тип интерфейса','interface-speeds':'Скорость интерфейса','connection-types':'Тип подключения','protocol-port-catalog':'Протокол / порт','embedded-os':'Встроенная ОС','software-assets':'Программный актив'};
const quickFields={
 'support-organizations':[['name','Наименование','text',true],['short_name','Краткое наименование','text',false],['description','Описание','textarea',false]],
 organizations:[['name','Наименование','text',true],['short_name','Краткое наименование','text',false],['description','Описание','textarea',false]],
 departments:[['name','Наименование','text',true],['parent_id','Родительское подразделение','fk',false]],
 buildings:[['name','Наименование','text',true],['address','Адрес','text',false]],
 rooms:[['building_id','Здание','fk',true],['name','Наименование помещения','text',true]],
 racks:[['room_id','Помещение','fk',true],['name','Наименование стойки','text',true],['height_u','Высота U','number',false]],
 'device-types':[['name','Наименование','text',true]],
 manufacturers:[['name','Наименование','text',true]],
 'device-models':[['device_type_id','Тип устройства','fk',true],['manufacturer_id','Производитель','fk',true],['model','Модель','text',true]],
 'os-categories':[['name','Наименование','text',true],['description','Описание','textarea',false]],
 'operating-systems':[['category_id','Категория ОС','fk',true],['name','Наименование ОС','text',true],['version','Версия','text',false],['vendor','Производитель','text',false],['description','Описание','textarea',false]],
 'interface-types':[['name','Наименование','text',true],['description','Описание','textarea',false]],
 'interface-speeds':[['name','Скорость','text',true],['description','Описание','textarea',false]],
 'connection-types':[['name','Наименование','text',true],['description','Описание','textarea',false]],
 'protocol-port-catalog':[['port','Номер порта','number',true],['protocol_type','Тип протокола','text',true],['description','Описание','textarea',false]],
 'embedded-os':[['name','Наименование','text',true],['version','Версия','text',false],['vendor','Производитель','text',false],['description','Описание','textarea',false]],
  vlans:[['vlan_id','VLAN ID','number',true],['name','VLAN Name','text',true],['description','Описание','textarea',false]],
 'vlan-domains':[['name','Наименование домена','text',true],['description','Описание','textarea',false],['auto_sync','Автосинхронизация','checkbox',false]],
 'support-methods':[['name','Наименование','text',true],['description','Описание','textarea',false]],
 'software-assets':[['name','Наименование','text',true],['category','Категория','text',false],['vendor','Производитель','text',false],['version','Версия','text',false],['description','Описание','textarea',false]],
 'placement-assets':[['name','Наименование','text',true],['description','Описание','textarea',false]],
 'crypto-protection-means':[['name','Наименование','text',true],['description','Описание','textarea',false]]
};
const labels={departments_summary:'Подразделения',support_organization_name:'Организация технической поддержки',protocols_summary:'Протоколы передачи данных',ip_addresses_summary:'IP-адреса ИС / внешнего взаимодействия',physical_devices_summary:'Физические серверы и другое оборудование',vms_summary:'Виртуальные машины',containers_summary:'Контейнеры',id:'ID',created_at:'Создано',updated_at:'Изменено',name:'Наименование',description:'Описание',number:'№',type:'Тип',purpose:'Назначение',localization:'Локализация',system_name:'Системное имя',serial_number:'Серийный номер',operating_system_id:'ОС',embedded_os_id:'Встроенная ОС',hypervisor_os_id:'Гипервизор',siem_enabled:'SIEM',building_id:'Здание',room_id:'Помещение',rack_id:'Стойка',rack_position:'Позиция',manufacturer_id:'Производитель',model_id:'Модель',device_type_id:'Тип устройства',physical_device_id:'Физическое устройство',ip_address:'IP адрес',prefix_length:'Префикс',is_management:'Управление',information_system_id:'Информационная система',department_id:'Подразделение',protocol:'Протокол',version:'Версия (legacy)',direction:'Направление (legacy)',port:'Порт протокола',external_interaction:'Внешнее взаимодействие',interface_type_id:'Тип интерфейса',mac_address:'MAC',speed_id:'Скорость',interface_id:'Интерфейс',vlan_id:'VLAN',domain_id:'Домен VLAN',mode:'Режим',vlan_summary:'VLAN',source_interface_id:'Исходный интерфейс',destination_interface_id:'Конечный интерфейс',connection_type_id:'Тип подключения',is_active:'Активно',vendor:'Производитель',runtime:'Runtime',runtime_version:'Версия runtime',container_id:'Контейнер',role:'Роль',software_asset_id:'Программный актив',category:'Категория',owner_type:'Тип владельца',owner_id:'Владелец',transport_protocol:'Транспорт',port:'Порт',crypto_protection_enabled:'СКЗИ',crypto_protection_description_id:'Описание СКЗИ',support_organization_id:'Организация технической поддержки',support_method_id:'Способ оказания технической поддержки',support_method_name:'Способ оказания технической поддержки',placement_assets_summary:'Оборудование, ПО, интерфейс на которых размещается ИС',process_description:'Процесс функционирования',short_name:'Краткое наименование',height_u:'Высота U',parent_id:'Родительское подразделение',status:'Состояние устройства',category_id:'Категория ОС',management_interface:'Порт управления',management_ips:'IP управления',interface_count:'Количество интерфейсов',source_device_name:'Исходное устройство',source_interface_name:'Исходный порт',destination_device_name:'Конечное устройство',destination_interface_name:'Конечный порт',connection_type_name:'Тип подключения'};
const resourceMap={'organizations':'organizations','support_organizations':'support-organizations','support_methods':'support-methods','departments':'departments','buildings':'buildings','rooms':'rooms','racks':'racks','device_types':'device-types','manufacturers':'manufacturers','device_models':'device-models','physical_devices':'devices','information_systems':'information-systems','information_system_departments':'is-departments','information_system_ips':'is-ips','information_system_protocols':'is-protocols','device_interfaces':'interfaces','interface_ips':'interface-ips','interface_types':'interface-types','interface_speeds':'interface-speeds','vlans':'vlans','vlan_domains':'vlan-domains','vlan_domain_devices':'vlan-domain-devices','interface_vlans':'interface-vlans','connection_types':'connection-types','connections':'connections','operating_system_categories':'os-categories','operating_systems':'operating-systems','embedded_operating_systems':'embedded-os','device_type_vlans':'device-type-vlans','physical_device_vlans':'device-vlans','virtual_machines':'vms','vm_ips':'vm-ips','containers':'containers','software_assets':'software-assets','device_software':'device-software','vm_software':'vm-software','information_system_devices':'is-devices','information_system_vms':'is-vms','information_system_containers':'is-containers','protocol_port_catalogs':'protocol-port-catalog'};
// Кеш в памяти на время сессии — только для схем ресурсов (меняются лишь миграциями БД, никогда
// в рантайме) и для действительно статичных справочников (типы устройств, производители и т.п.).
// Первичные данные (устройства, ВМ, подключения, интерфейсы, VLAN-назначения) НЕ кешируются —
// они меняются в ходе обычной работы слишком часто, риск показать устаревшие данные не стоит
// экономии одного запроса.
const CACHEABLE_LIST_RESOURCES = new Set(['device-types','manufacturers','device-models','interface-types','interface-speeds','connection-types','operating-systems','embedded-os','os-categories','support-organizations','support-methods','crypto-protection-means','placement-assets','protocol-port-catalog','buildings','rooms','racks','departments']);
const _resourceCache = new Map();
function _cacheKeyForUrl(url) {
  const [path, query] = url.split('?');
  const m = path.match(/^\/api\/v1\/resources\/([a-z-]+)(\/schema)?$/);
  if (!m) return null;
  const [, res, isSchema] = m;
  if (isSchema) return `schema:${res}`;
  if (CACHEABLE_LIST_RESOURCES.has(res) && query === 'limit=1000') return `list:${res}`;
  return null;
}
function _invalidateCacheForUrl(url) {
  const m = url.match(/^\/api\/v1\/resources\/([a-z-]+)/);
  if (m) _resourceCache.delete(`list:${m[1]}`);
}
// Единый разбор ошибок API. err.message — это тело HTTP-ответа как есть (см. get() ниже).
// Бэкенд использует detail либо как простую строку (большинство мест), либо как объект
// {code, message} там, где фронтенду нужно различать конкретный случай (диалог подтверждения
// дубликата, занятой позиции в стойке и т.п.). Без этой функции alert(errorMessage(err)) для строкового
// формата показывал пользователю сырой JSON целиком, например {"detail":"текст ошибки"}.
function parseApiError(err) {
  let detail = null;
  try { detail = JSON.parse(err.message)?.detail; } catch (_) {}
  if (typeof detail === 'string') return { code: null, message: detail };
  if (detail && typeof detail === 'object') return { code: detail.code || null, message: detail.message || err.message };
  return { code: null, message: err.message };
}
function errorMessage(err) { return parseApiError(err).message; }

// Единообразные toast-уведомления вместо alert(): не блокируют интерфейс, автоматически
// скрываются через notifyMs (кроме ошибок — те остаются, пока их не закроют, чтобы не
// пропустить сообщение о проблеме). type: 'error' | 'success' | 'info'.
function _toastContainer(){
  let el=document.getElementById('toast-container');
  if(!el){el=document.createElement('div');el.id='toast-container';document.body.appendChild(el);}
  return el;
}
function notify(message,type='info'){
  const container=_toastContainer();
  const el=document.createElement('div');
  el.className=`toast ${type}`;
  const text=document.createElement('span');text.textContent=message;el.appendChild(text);
  const closeBtn=document.createElement('button');closeBtn.className='toast-close';closeBtn.setAttribute('aria-label','Закрыть');closeBtn.textContent='×';
  closeBtn.onclick=()=>el.remove();
  el.appendChild(closeBtn);
  container.appendChild(el);
  if(type!=='error') setTimeout(()=>el.remove(),5000);
}
function notifyError(err){notify(errorMessage(err),'error');}

// Переводит кнопку в состояние "выполняется" (disabled, текст с многоточием) на время async-
// действия и восстанавливает исходное состояние в finally — для операций без собственного
// индикатора загрузки (генерация отчёта, синхронизация VLAN-домена и т.п.), чтобы пользователь
// не решил, что клик не сработал, и не отправил запрос повторно, пока предыдущий ещё выполняется.
async function withBusyButton(btn,fn){
  if(!btn) return fn();
  const original=btn.textContent,wasDisabled=btn.disabled;
  btn.disabled=true;btn.textContent=original+'…';
  try{ return await fn(); }
  finally{ btn.disabled=wasDisabled;btn.textContent=original; }
}

async function get(url,opt){
  const method=(opt&&opt.method)||'GET';
  if(method==='GET'){
    const key=_cacheKeyForUrl(url);
    if(key&&_resourceCache.has(key))return _resourceCache.get(key);
    const r=await fetch(url,opt);if(!r.ok){const t=await r.text();throw Error(t||r.statusText)}
    const data=r.status===204?null:await r.json();
    if(key)_resourceCache.set(key,data);
    return data;
  }
  const r=await fetch(url,opt);if(!r.ok){const t=await r.text();throw Error(t||r.statusText)}
  _invalidateCacheForUrl(url);
  return r.status===204?null:r.json();
}
function esc(v){return String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
function formatValue(v){if(typeof v==='boolean')return v?'Да':'Нет';return v??''}
function lookupLabel(res,o){
 if(res==='device-models')return [o.model,o.name].filter(Boolean).join(' — ');
 if(res==='embedded-os')return [o.name,o.version].filter(Boolean).join(' ');
 if(res==='operating-systems')return [o.name,o.version].filter(Boolean).join(' ');
 if(res==='devices')return o.system_name||o.serial_number||o.id;
 if(res==='interfaces')return [o.name,o.mac_address].filter(Boolean).join(' / ');
 if(res==='interface-speeds'||res==='interface-types'||res==='connection-types')return o.name||o.id;
 if(res==='information-systems')return o.name||o.id;
 if(res==='support-organizations')return o.name||o.short_name||o.id;
 if(res==='protocol-port-catalog')return [o.port,o.protocol_type].filter(v=>v!==undefined&&v!==null&&v!=='').join(' / ')||o.id;
 if(res==='vms')return o.name||o.id;
 return o.name||o.short_name||o.system_name||o.serial_number||o.ip_address||o.model||o.id;
}
