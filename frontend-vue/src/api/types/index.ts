// Типы отражают реальные поля моделей бэкенда (backend/app/models.py) и то, что
// действительно возвращают эндпоинты (backend/app/services/serialization.py) —
// см. serialize(): отдаёт сырые колонки как есть, без резолва FK в имена.
// Резолв имён — задача фронтенда (см. stores/catalogs.ts), как и в прежнем
// vanilla-фронтенде (до 2.60.0: lookupLabel/resourceMap).
//
// R2-06 (ревью merge/review-f06-stage2-f05-executors): файл на 1 281 строку разбит по доменам; импорты из '../api/types' работают как прежде —
// этот индекс реэкспортирует всё. Новые типы добавляйте в модуль своего домена.

export * from './catalogs'
export * from './devices'
export * from './interfaces'
export * from './connections'
export * from './vlans'
export * from './stacks'
export * from './workloads'
export * from './informationSystems'
export * from './reports'
export * from './portSync'
export * from './audit'
export * from './auth'
