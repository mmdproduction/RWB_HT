import json
from pathlib import Path
import zipfile

from shared.models import STACK


def documents(root:Path,spec:dict|None,results:list,summary:str,app_url=None):
    docs=root/'reports'; docs.mkdir(exist_ok=True)
    spec=spec or {}
    write=lambda name,body:(docs/name).write_text(body,encoding='utf-8')
    write('product.md','# '+spec.get('title','Запуск')+'\n\n'+spec.get('summary','')+
        '\n\n## Цель\n\n'+spec.get('businessGoal','')+'\n\n## Главное действие\n\n'+spec.get('primaryAction','')+
        '\n\n## Экраны\n\n'+'\n'.join('- '+s['name']+': '+s['purpose'] for s in spec.get('screens',[]))+
        '\n\n## Не входит в задачу\n\n'+'\n'.join('- '+item for item in spec.get('outOfScope',[]))+'\n\n## Требования\n\n'+
        '\n'.join('### '+r['id']+' — '+r['description']+'\n\n'+'\n'.join('- '+a for a in r['acceptance'])+'\n' for r in spec.get('requirements',[]))+
        '\n## Допущения\n\n'+'\n'.join('- '+a for a in spec.get('assumptions',[])))
    write('system-analysis.md','# Системный анализ\n\nРоли: '+', '.join(spec.get('roles',[]))+'\n\n'+
        '\n\n'.join('## '+w['name']+'\n\n'+w['description']+'\n\nТребования: '+', '.join(w['requirementIds']) for w in spec.get('workflows',[]))+
        '\n\nВопросы:\n'+json.dumps(spec.get('questions',[]),ensure_ascii=False,indent=2))
    write('architecture.md','# Архитектура\n\n'+json.dumps(STACK,ensure_ascii=False,indent=2)+
        '\n\nБраузер/PWA → Nginx /api → ASP.NET Core → PostgreSQL/PostGIS. Раздельные контейнеры, healthchecks и постоянный volume. '
        'Предметные расширения Qwen подключаются через GeneratedExtensions и GeneratedPanel. Данные общих сущностей хранятся в JSONB с проверкой полей. '+
        'Внешний GitLab runner в этом запуске не использовался: .gitlab-ci.yml приложен, фактическая сборка выполнена локально Docker Compose.')
    write('mock-integrations.md','# Внешние интеграции — mock\n\nВнешние сервисы заменены локальными провайдерами. Реальные деньги не списываются, сообщения не отправляются, данные и карты демонстрационные. '
        'Контракты и fixtures: project/docs/mock-integrations.json. Реальные вызовы, отказы и квитанции сохраняются в PostgreSQL. '
        'Сборка и работа самого пайплайна могут использовать сеть; runtime backend приложения изолирован.\n\n```json\n'+
        json.dumps(spec.get('externalIntegrations',[]),ensure_ascii=False,indent=2)+'\n```')
    write('data-model.md','# Модель данных\n\n```json\n'+json.dumps(spec.get('entities',[]),ensure_ascii=False,indent=2)+'\n```\n\nФизическая схема: project/backend/schema.sql. '
        'Миграция выполняется идемпотентно при запуске API. JSONB-сущности имеют прикладную валидацию; это прототип, не набор отдельных типизированных таблиц.')
    write('launch.md','# Запуск\n\nСкачайте project.zip. Создайте .env с уникальным DB_PASSWORD (пример .env.example). '
        'В каталоге проекта: `docker compose up -d --build --wait`. Узнайте порт: `docker compose port frontend 80`. '
        'Проверки: `docker compose --profile checks run --rm checks`. '
        'Остановка с сохранением БД: `docker compose down`. Удаление БД только явно: `docker compose down -v`.\n\nТекущий адрес: '+str(app_url or 'не развернуто'))
    login=('Выберите демонстрационную роль. Вход предназначен только для локальной демонстрации. ' if spec.get('requiresLogin',True) else
        'Приложение открывается сразу, отдельный вход не нужен. Технический demo-токен не является учетной записью пользователя. ')
    parking=('Водитель явно запускает и останавливает сессию. Смена/покидание зоны дает подсказку; предупреждение появляется за 10 минут до окончания. ' if 'parking' in spec.get('capabilities',[]) else '')
    write('user-guide.md','# Пользователь\n\n'+login+spec.get('primaryAction','')+'\n\n'+
        '\n'.join('- '+s['name']+': '+s['purpose'] for s in spec.get('screens',[]))+'\n\n'+parking+
        'PWA: локальный localhost или HTTPS; на удаленном HTTP установка/геолокация могут быть недоступны.')
    write('developer-guide.md','# Разработчик\n\nИсходники: frontend/ (Angular), backend/ (.NET), db/, scripts/. '
        'Контракты: app-spec.json и docs/openapi.json. Расширения: backend/Generated и frontend/src/app/generated. '
        'Модель не меняет инфраструктуру и базовые проверки. После изменения кода повторите build и обе группы HTTP acceptance. '
        'Секреты только в локальном .env; он исключен из архива.')
    write('verification.md','# Фактические результаты\n\n'+summary+'\n\n'+
        '\n'.join('- '+r['name']+': returnCode='+str(r.get('returnCode'))+', '+str(r.get('durationSeconds',''))+' s; '+r.get('report','') for r in results)+
        '\n\nМодельные HTTP сценарии не являются независимым доказательством полноты ТЗ. Базовые проверки заданы разработчиком. '
        'Подробные команды, stdout/stderr и return codes сохранены в JSON и log рядом с отчетом.')
    write('limitations.md','# Ограничения\n\n- Демо-авторизация: любой посетитель может выбрать admin. Только локальная доверенная среда.\n'
        '- Нет реальных платежей, промышленного SSO, фонового мобильного GPS и гарантий доставки push.\n'
        '- Геолокация/карта и парковочные события работают в активном PWA; продление/завершение подтверждает водитель.\n'
        '- Зависимости стека фиксированы заданием; аудит уязвимостей информационный, находки не скрываются и не исправляются сменой версии.\n'
        '- Worker управляет Docker; не предназначен для публичного приема недоверенного кода.\n'
        '- Полнота бизнес-требований требует ручной приемки. Генерируемые тесты дополняют фиксированные, но не заменяют ее.\n'
        '- Репозиторий/внешний GitLab не создавались.\n')
    generation_path=docs/'generation.json'
    generation=json.loads(generation_path.read_text()) if generation_path.exists() else {}
    domain_tests=generation.get('acceptanceTests',[])
    frozen_tests=root/'project/scripts/domain-acceptance.json'
    if frozen_tests.exists(): domain_tests=json.loads(frozen_tests.read_text())
    write('traceability.md','# Трассировка требований\n\nСтрока означает наличие требований в модели и ссылок в предметных тестах; полноту реализации необходимо подтвердить ручной приемкой. '
        'Фиксированные тесты проверяют общий CRUD, роли, PWA, перезапуск и при наличии parking — парковочный сценарий.\n\n'
        '| ID | Требование | Предметные HTTP-сценарии |\n|---|---|---|\n'+
        '\n'.join('| '+r['id']+' | '+r['description'].replace('|','/').replace('\n',' ')+' | '+
            (', '.join(t['name'] for t in domain_tests if r['id'] in t.get('requirementIds',[])) or 'Только общие проверки / нужна ручная приемка')+' |' for r in spec.get('requirements',[]))+
        '\n\n## Примечания генерации\n\n'+'\n'.join('- '+str(note) for note in generation.get('implementationNotes',[])))
    write('api.md','# API\n\nПолный контракт основы: `project/docs/openapi.json`. Общие сущности: `/api/entities/{Entity}`, методы GET/POST/PUT/DELETE. '
        'Вход: POST `/api/auth/login` с role; дальше Authorization: Bearer token. Парковочные маршруты перечислены в OpenAPI.\n\n'
        'Предметные маршруты из acceptance:\n\n'+'\n'.join('- `'+step['method']+' '+step['path']+'` — '+t['name'] for t in domain_tests for step in t['steps']))


def source_archive(project:Path,target:Path):
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(project.rglob('*')):
            relative=path.relative_to(project)
            if path.is_symlink() or not path.is_file() or any(part in {'.env','.git','node_modules','bin','obj','dist','.angular','__pycache__'} for part in relative.parts):
                continue
            archive.write(path,str(relative))
