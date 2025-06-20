#!/usr/bin/env python3

import asyncio
import jinja2
import logging
import re
import yaml

from bot_dialogs import Account, Session


logger = logging.getLogger(__name__)

WATERIUS_VALUE_PATTERN = r"\(([-\d]+)\) — ([\.\d]+) м"

async def get_values(session: Session):
    async with session.dialog("waterius_official_bot") as bot:
        await bot.send("/start")
        await bot.wait(answer=". Получить показания")
        result = await bot.wait()
        return dict(re.findall(WATERIUS_VALUE_PATTERN, result.message))


async def send_tomrc(session: Session, account_number, values):
    counters = {
        "счётчика на холодную воду ,в кухне": "25-057961",
        "счётчика на холодную воду ,в санузле": "25-065086",
        "счётчика на горячую воду ,в санузле": "25-010833",
        "счётчика на горячую воду ,в кухне": "25-079292",
    }
    info = {}
    async with session.dialog("tomrc70_bot") as bot:
        await bot.send("/start")
        await bot.seek("Передать показания приборов учёта воды", "Главное меню", "В главное меню", "Пропустить")
        await bot.wait("ВНИМАНИЕ ! Показания счетчиков следует передавать ежемесячно")
        await bot.wait("Ваш лицевой счет")
        await bot.send(account_number)
        await bot.wait("Ваш адрес Томская обл, Томск г, Соляной пер, д. 17, кв. 24?", answer="Да")
        await bot.wait(r"Лицевой счет \S+ успешно найден")
        await bot.wait("Оставьте, пожалуйста, контактный телефон", answer="Пропустить")
        for i in range(len(values)):
            name, prev_value = await bot.match(r"Введите показания \d (.+), с предыдущими показаниями ([\d\.]+)")
            code = counters[name]
            info[code] = {
                "prev_value": prev_value,
                "curr_value": values[code],
            }
            await bot.send(values[code])
            usage, = await bot.match(r"Ваш расход составил ([\d\.]+)")
            info[code]["usage"] = usage
        await bot.wait("Показания сохранены")
    return info


async def send_tes(session: Session, account_number, values):
    info = {}
    async with session.dialog("tes_telegram_bot") as bot:
        await bot.send("/start")
        await bot.seek("Передача показаний")
        await bot.wait("Укажите полный лицевой счёт")
        await bot.send(account_number)
        await bot.wait("Томск г., Соляной пер, 17, 24")
        await bot.wait("Верна ли информация?", answer="Верно")
        while True:
            msg = await bot.wait("Выберите услугу/счётчик")
            for button in msg.buttons:
                match = button.matches(r"\s*ГВС / (\S+)")
                if match and match.group(1) not in info:
                    code = match.group(1)
                    curr_value = values[code]
                    await button.click()
                    prev_value, = await bot.match(r"Предыдущие показания: (\S+)")
                    await bot.wait("Введите актуальные показания:")
                    await bot.send(curr_value)
                    await bot.wait(r"Дата снятия показаний (\S+) ?", answer="Да, использовать текущую дату")
                    await bot.wait("Показания приняты, продолжить передачу показаний?", answer="Выбрать другой прибор")
                    info[code] = {
                        "prev_value": prev_value,
                        "curr_value": curr_value,
                    }
                    break
            else:
                button = next(button for button in msg.buttons if button.matches("Назад в меню"))
                await button.click()
                break
    return info


REPORT_TEMPLATE = """
{%- macro print_counters(info) -%}
    {{ caller() }}:
    {%- for key, val in info|dictsort %}
    - {{key}}: {{val["prev_value"]}} -> {{val["curr_value"]}}
    {%- endfor -%}
{%- endmacro -%}
Отправлены показания счетчиков.
{% call print_counters(tomrc_info) %}Водоснабжение и водоотведение{% endcall %}
{% call print_counters(tes_info) %}Теплоснабжение{% endcall %}
"""

async def report(session: Session, report_id, tomrc_info, tes_info):
    template = jinja2.Template(REPORT_TEMPLATE)
    report = template.render(tomrc_info=tomrc_info, tes_info=tes_info)
    async with session.dialog(report_id) as dialog:
        await dialog.send(report)


async def amain():
    with open("config.yaml") as file:
        config = yaml.safe_load(file)
        account = Account(**config["account"])
        report_id = config.get("report_id")

    async with Session(account) as session:
        values = await get_values(session)
        logger.info("Got values: %s", values)
        tomrc_info = await send_tomrc(session, account_number="490381", values=values)
        logger.info("Sent info to tomrc: %s", tomrc_info)
        tes_info = await send_tes(session, account_number="234864", values=values)
        logger.info("Sent info to tes: %s", tes_info)
        if report_id:
            await report(session, report_id, tomrc_info, tes_info)

if __name__ == "__main__":
    logging.basicConfig(level="INFO")

    asyncio.run(amain())
