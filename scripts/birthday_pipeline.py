"""ai-takt: Birthday Pipeline
За 5 дней до месяца проверяет employee_base.xlsx на именинников в следующем месяце,
генерирует текст + изображение поздравления и отправляет ЛПР на утверждение.

Запуск: python scripts/birthday_pipeline.py
"""
import sys, os, json, asyncio
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

# Путь к Excel
EXCEL_PATH = r'C:\Users\User\Ouroboros\Deliverables\excel_data\employee_base.xlsx'
DELIVERABLES_DIR = r'C:\Users\User\Ouroboros\Deliverables'

# ── 1. Чтение именинников следующего месяца ──
def get_next_month_birthdays():
    """Возвращает список сотрудников, у которых ДР в следующем месяце."""
    try:
        import openpyxl
    except ImportError:
        print(json.dumps({"error": "openpyxl not installed"}))
        return []

    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    # Определяем заголовки
    headers = {cell.value: idx for idx, cell in enumerate(ws[1])}
    
    now = datetime.now()
    # Следующий месяц: если сейчас декабрь, то январь
    if now.month == 12:
        next_month = 1
        next_year = now.year + 1
    else:
        next_month = now.month + 1
        next_year = now.year
    
    birthday_col = headers.get('birthday')
    fio_col = headers.get('last, first name') or headers.get('FIO') or headers.get('ФИО')
    hobby_col = headers.get('hobby')
    info_col = headers.get('info')
    
    birthdays = []
    for row in ws.iter_rows(min_row=2, values_only=False):
        vals = [c.value for c in row]
        if not any(vals):
            continue
        
        birthday_val = vals[birthday_col] if birthday_col is not None and birthday_col < len(vals) else None
        name = vals[fio_col] if fio_col is not None and fio_col < len(vals) else None
        
        if not birthday_val or not name:
            continue
        
        # Парсим дату
        bday = None
        if isinstance(birthday_val, datetime):
            bday = birthday_val
        elif isinstance(birthday_val, str):
            for fmt in ['%d.%m.%Y', '%d.%m.%y', '%Y-%m-%d']:
                try:
                    bday = datetime.strptime(birthday_val, fmt)
                    break
                except ValueError:
                    continue
        elif hasattr(birthday_val, 'month'):
            bday = birthday_val
        
        if bday and bday.month == next_month:
            hobbies = vals[hobby_col] if hobby_col is not None and hobby_col < len(vals) else ''
            info = vals[info_col] if info_col is not None and info_col < len(vals) else ''
            birthdays.append({
                'name': str(name).strip(),
                'birthday': bday.strftime('%d.%m'),
                'hobby': str(hobbies).strip() if hobbies else '',
                'info': str(info).strip() if info else ''
            })
    
    wb.close()
    return birthdays


# ── 2. Генерация текста поздравления ──
def generate_congratulation_text(employee):
    """Генерирует персонализированный текст поздравления."""
    name = employee['name']
    hobbies = employee.get('hobby', '')
    info = employee.get('info', '')
    
    # Определяем обращение
    names = name.split()
    first_name = names[0] if names else name
    
    # Персонализируем текст
    personal_lines = []
    if hobbies:
        personal_lines.append(f"Ваше увлечение — {hobbies.lower().strip('.')} — делает Вас уникальным.")
    if info:
        personal_lines.append(info.strip('.'))
    
    personal_section = '\n'.join(personal_lines) if personal_lines else ""
    
    text = (
        f"Дорогой {first_name}!\n\n"
        f"От всей команды поздравляем Вас с днём рождения!\n\n"
    )
    if personal_section:
        text += personal_section + "\n\n"
    text += (
        "Желаем Вам ярких побед, крепкого здоровья, "
        "вдохновения и гармонии в каждом дне. "
        "Пусть рядом будут надёжные друзья и единомышленники!\n\n"
        "С наилучшими пожеланиями, команда ai_takt"
    )
    return text


# ── 3. Генерация изображения через OpenRouter ──
async def generate_birthday_image(employee):
    """Генерирует картинку через OpenRouter gpt-5-image-mini."""
    import openrouter as or_requests
    
    name = employee['name']
    hobby = employee.get('hobby', '')
    info = employee.get('info', '')
    
    # Собираем промпт
    themes = ['тёплая атмосфера', 'золотой рассвет', 'уют']
    if 'бег' in hobby.lower() or 'спорт' in hobby.lower() or 'лыж' in hobby.lower() or 'велосипед' in hobby.lower():
        themes = ['спортивная иллюстрация', 'парк на рассвете', 'беговая дорожка', 'энергия']
    elif 'музык' in hobby.lower():
        themes = ['музыкальная иллюстрация', 'тёплый свет', 'ноты в воздухе']
    elif 'книг' in hobby.lower() or 'чита' in hobby.lower():
        themes = ['уютная библиотека', 'книги', 'тёплый свет']
    
    prompt = (
        f"Нарисуй тёплую праздничную иллюстрацию для {name}: "
        f"{', '.join(themes)}. "
        f"Стиль: уютная flat-иллюстрация с мягким светом. "
        f"Без текста и надписей на картинке."
    )
    
    # Сохраняем промпт для отчёта
    return {"prompt": prompt, "model": "openai/gpt-5-image-mini", "themes": themes}


# ── 4. Формирование отчёта для ЛПР ──
def format_report(birthdays):
    """Формирует отчёт для отправки ЛПР."""
    if not birthdays:
        return None
    
    report_lines = [
        "📋 **ПРЕДВАРИТЕЛЬНЫЙ ОТЧЁТ: Поздравления на следующий месяц**",
        "",
        f"Обнаружено именинников: {len(birthdays)}",
        ""
    ]
    
    for emp in birthdays:
        report_lines.append(f"---")
        report_lines.append(f"**{emp['name']}** — {emp['birthday']}")
        if emp['hobby']:
            report_lines.append(f"  • Хобби: {emp['hobby']}")
        if emp['info']:
            report_lines.append(f"  • Инфо: {emp['info']}")
        
        text_preview = generate_congratulation_text(emp)
        report_lines.append(f"")
        report_lines.append(f"📝 Текст поздравления:")
        report_lines.append(f"```")
        report_lines.append(text_preview)
        report_lines.append(f"```")
        
        img = asyncio.run(generate_birthday_image(emp))
        report_lines.append(f"")
        report_lines.append(f"🖼️ Концепция картинки: {', '.join(img['themes'])}")
        report_lines.append(f"")
    
    report_lines.append(f"---")
    report_lines.append(f"")
    report_lines.append(f"⚠️ **Требуется ваше утверждение:**")
    report_lines.append(f"Пожалуйста, подтвердите или отредактируйте контент.")
    
    return "\n".join(report_lines)


if __name__ == "__main__":
    print("🎂 Birthday Pipeline запущен...")
    
    birthdays = get_next_month_birthdays()
    if not birthdays:
        print(json.dumps({"status": "no_birthdays", "next_month": None}))
        print("Нет именинников в следующем месяце. Пропускаем.")
        sys.exit(0)
    
    report = format_report(birthdays)
    print(report)
    
    print("")
    print(json.dumps({
        "status": "report_ready",
        "employee_count": len(birthdays),
        "employees": [b['name'] for b in birthdays]
    }))
