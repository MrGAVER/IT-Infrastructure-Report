// csv-import.js — импорт устройств из CSV-файла (полностью автономный оверлей поверх страницы,
// не #modal, поэтому не пересекается с состоянием обычных форм — formOpenSnapshot/editingId/
// resource). Создание записей идёт через тот же самый /resources/devices POST, что и обычная
// форма — отдельной логики создания нет.
//
// Третий шаг разбиения app.js на несколько обычных <script> (см.
// docs/frontend-modularization.md, вариант C) — самодостаточный блок, единственная связь с
// остальным app.js — вызов openCsvImport() из кнопки на экране списка устройств (renderTable()).
// Может подключаться в любом порядке относительно app.js/vm-editors.js — ничего из этого файла
// не вызывается на верхнем уровне при загрузке страницы, только по клику пользователя.

// CSV-импорт устройств — полностью автономный оверлей (не #modal), поэтому не пересекается с
// состоянием обычных форм (formOpenSnapshot/editingId/resource). Создание записей идёт через
// тот же самый /resources/devices POST, что и обычная форма — новой логики создания нет.
function csvParse(text) {
  const rows = []; let row = [], field = '', inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') { if (text[i+1] === '"') { field += '"'; i++; } else inQuotes = false; }
      else field += c;
    } else if (c === '"') inQuotes = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i+1] === '\n') i++;
      row.push(field); field = '';
      if (row.length > 1 || row[0] !== '') rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== '' || row.length) { row.push(field); rows.push(row); }
  return rows;
}
function openCsvImport(){
  const overlay=document.createElement('div');
  overlay.id='csvImportOverlay';overlay.className='modal show';
  overlay.innerHTML=`<div class="dialog">
    <div class="top"><h2>Импорт устройств из CSV</h2><button class="btn gray" onclick="closeCsvImport()">Закрыть</button></div>
    <div class="muted" style="margin:8px 0">Колонки (первая строка — заголовки, порядок и регистр не важны):
    <b>Тип устройства, Производитель, Модель, Серийный номер, Системное имя, Здание, Помещение, Стойка, Позиция</b>.
    Обязательны только «Тип устройства» и «Серийный номер». Остальные поля ищутся по названию в
    соответствующих справочниках — если название не найдено, поле останется пустым, запись всё
    равно будет создана.</div>
    <input type="file" id="csvFileInput" accept=".csv,text/csv">
    <div id="csvImportResult" style="margin-top:12px"></div>
  </div>`;
  document.body.appendChild(overlay);
  document.getElementById('csvFileInput').addEventListener('change',handleCsvFileSelected);
}
function closeCsvImport(){document.getElementById('csvImportOverlay')?.remove();}
async function handleCsvFileSelected(e){
  const file=e.target.files[0];if(!file)return;
  const resultBox=document.getElementById('csvImportResult');
  resultBox.innerHTML='<div class="muted">Обработка…</div>';
  const text=await file.text();
  const rows=csvParse(text).filter(r=>r.some(c=>c.trim()!==''));
  if(!rows.length){resultBox.innerHTML='<div class="muted">Файл пуст.</div>';return;}
  const header=rows[0].map(h=>h.trim().toLowerCase());
  const dataRows=rows.slice(1);
  const idx=name=>header.indexOf(name);
  const colType=idx('тип устройства'),colMfr=idx('производитель'),colModel=idx('модель'),colSerial=idx('серийный номер'),colName=idx('системное имя'),colBuilding=idx('здание'),colRoom=idx('помещение'),colRack=idx('стойка'),colPos=idx('позиция');
  if(colType===-1||colSerial===-1){resultBox.innerHTML='<div class="muted">В файле должны быть колонки «Тип устройства» и «Серийный номер».</div>';return;}
  const [deviceTypes,manufacturers,models,buildings,rooms,racks]=await Promise.all([
    get(api+'/resources/device-types?limit=1000').then(r=>r.items),
    get(api+'/resources/manufacturers?limit=1000').then(r=>r.items),
    get(api+'/resources/device-models?limit=1000').then(r=>r.items),
    get(api+'/resources/buildings?limit=1000').then(r=>r.items),
    get(api+'/resources/rooms?limit=1000').then(r=>r.items),
    get(api+'/resources/racks?limit=1000').then(r=>r.items),
  ]);
  const byName=(list,name)=>name?list.find(x=>(x.name||'').trim().toLowerCase()===name.trim().toLowerCase()):null;
  const byModel=(name,mfrId,typeId)=>name?models.find(x=>(x.model||'').trim().toLowerCase()===name.trim().toLowerCase()&&(!mfrId||x.manufacturer_id===mfrId)&&(!typeId||x.device_type_id===typeId)):null;
  const results=[];
  for(let i=0;i<dataRows.length;i++){
    const row=dataRows[i];
    const typeName=(row[colType]||'').trim(),serial=(row[colSerial]||'').trim();
    if(!typeName||!serial){results.push({row:i+2,ok:false,message:'Не заполнено «Тип устройства» или «Серийный номер» — строка пропущена'});continue;}
    const deviceType=byName(deviceTypes,typeName);
    if(!deviceType){results.push({row:i+2,ok:false,message:`Тип устройства «${typeName}» не найден в справочнике`});continue;}
    const manufacturer=colMfr!==-1?byName(manufacturers,row[colMfr]):null;
    const model=colModel!==-1?byModel(row[colModel],manufacturer?.id,deviceType.id):null;
    const building=colBuilding!==-1?byName(buildings,row[colBuilding]):null;
    const room=colRoom!==-1?byName(rooms,row[colRoom]):null;
    const rack=colRack!==-1?byName(racks,row[colRack]):null;
    const data={device_type_id:deviceType.id,manufacturer_id:manufacturer?.id||model?.manufacturer_id||null,model_id:model?.id||null,serial_number:serial,system_name:colName!==-1?((row[colName]||'').trim()||null):null,building_id:building?.id||null,room_id:room?.id||null,rack_id:rack?.id||null,rack_position:colPos!==-1?((row[colPos]||'').trim()||null):null};
    try{await get(api+'/resources/devices',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});results.push({row:i+2,ok:true,message:`${typeName} / ${serial} — создано`});}
    catch(err){results.push({row:i+2,ok:false,message:`${serial}: ${errorMessage(err)}`});}
  }
  const okCount=results.filter(r=>r.ok).length;
  resultBox.innerHTML=`<div class="muted">Готово: ${okCount} из ${results.length} строк создано.</div><div class="nested-list" style="max-height:300px">${results.map(r=>`<div class="nested-row" style="grid-template-columns:80px 1fr"><span>${r.ok?'✅':'❌'} стр. ${r.row}</span><span>${esc(r.message)}</span></div>`).join('')}</div><button class="btn" style="margin-top:10px" onclick="closeCsvImport();renderList()">Готово</button>`;
}
