from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import GENERATED_DIR, STATIC_CONTRACT_PATH, Settings
from app.services.dates import format_iso_dates_ru, parse_dates_to_iso


FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
]


def register_cyrillic_font() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            pdfmetrics.registerFont(TTFont("AppSans", path))
            return "AppSans"
    # Helvetica не поддерживает кириллицу, но оставляем fallback, чтобы код не падал.
    return "Helvetica"


def _styles() -> dict[str, ParagraphStyle]:
    font = register_cyrillic_font()
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleRu",
            parent=styles["Title"],
            fontName=font,
            fontSize=16,
            leading=20,
            alignment=1,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "H2Ru",
            parent=styles["Heading2"],
            fontName=font,
            fontSize=12,
            leading=15,
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "BodyRu",
            parent=styles["BodyText"],
            fontName=font,
            fontSize=9.5,
            leading=13,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "SmallRu",
            parent=styles["BodyText"],
            fontName=font,
            fontSize=8,
            leading=10,
        ),
    }


def p(text: str, style: ParagraphStyle) -> Paragraph:
    safe = text.replace("\n", "<br/>")
    return Paragraph(safe, style)


def _build_pdf(path: Path, settings: Settings, booking: Any | None = None, dates: list[str] | None = None) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )

    today = datetime.now(settings.tz).strftime("%d.%m.%Y")
    client_name = booking["client_name"] if booking else "____________________________"
    client_phone = booking["phone"] if booking else "____________________________"
    client_address = booking["address"] if booking else "____________________________"
    delivery = booking["delivery_required"] if booking else "____________________________"
    comment = booking["comment"] if booking and booking["comment"] else "-"

    if dates:
        dates_text = format_iso_dates_ru(dates)
    elif booking:
        try:
            dates_text = format_iso_dates_ru(parse_dates_to_iso(booking["requested_dates_text"]))
        except Exception:
            dates_text = booking["requested_dates_text"]
    else:
        dates_text = "____________________________"

    story = []
    story.append(p("ДОГОВОР АРЕНДЫ РОБОТА-МОЙЩИКА ОКОН", styles["title"]))
    story.append(p(f"Дата: {today}", styles["body"]))

    party_data = [
        [p("Арендодатель", styles["small"]), p(settings.company_name, styles["small"])],
        [p("ИНН", styles["small"]), p(settings.company_inn or "-", styles["small"])],
        [p("Телефон", styles["small"]), p(settings.company_phone or "-", styles["small"])],
        [p("Адрес", styles["small"]), p(settings.company_address or "-", styles["small"])],
        [p("Email", styles["small"]), p(settings.company_email or "-", styles["small"])],
        [p("Арендатор", styles["small"]), p(client_name, styles["small"])],
        [p("Телефон арендатора", styles["small"]), p(client_phone, styles["small"])],
        [p("Адрес использования", styles["small"]), p(client_address, styles["small"])],
        [p("Даты аренды", styles["small"]), p(dates_text, styles["small"])],
        [p("Доставка", styles["small"]), p(delivery, styles["small"])],
        [p("Комментарий", styles["small"]), p(comment, styles["small"])],
    ]
    table = Table(party_data, colWidths=[45 * mm, 115 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 8))

    sections = [
        (
            "1. Предмет договора",
            "Арендодатель передает Арендатору во временное пользование робота-мойщика окон, "
            "комплектующие и инструкцию по эксплуатации. Арендатор обязуется использовать оборудование "
            "бережно, по назначению и вернуть его в согласованный срок.",
        ),
        (
            "2. Срок аренды и возврат",
            "Срок аренды указан в таблице выше. Возврат оборудования производится не позднее согласованной даты. "
            "При необходимости продления срока Арендатор заранее согласовывает это с Арендодателем.",
        ),
        (
            "3. Залог и оплата",
            "Размер аренды, залога, доставки и дополнительных услуг согласуется сторонами отдельно до передачи оборудования. "
            "Залог возвращается после проверки комплектности и работоспособности робота, если отсутствуют повреждения и задолженность.",
        ),
        (
            "4. Ответственность сторон",
            "Арендатор отвечает за сохранность оборудования с момента получения до момента возврата. "
            "При повреждении, утрате или некомплектном возврате Арендатор компенсирует расходы на ремонт, замену или восстановление комплектующих.",
        ),
        (
            "5. Безопасность использования",
            "Арендатор подтверждает, что ознакомился с инструкцией, правилами крепления страховочного шнура, "
            "ограничениями по типу стекол и условиями безопасной эксплуатации. Запрещается использовать робот вне инструкции.",
        ),
        (
            "6. Прочие условия",
            "Настоящий шаблон договора может быть адаптирован под ваши юридические требования. "
            "Перед массовым использованием рекомендуется проверить текст у юриста.",
        ),
    ]
    for title, body in sections:
        story.append(p(title, styles["h2"]))
        story.append(p(body, styles["body"]))

    story.append(Spacer(1, 14))
    sign_data = [
        [p("Арендодатель", styles["body"]), p("Арендатор", styles["body"])],
        [p("Подпись: ____________________", styles["body"]), p("Подпись: ____________________", styles["body"])],
        [p("ФИО: ________________________", styles["body"]), p("ФИО: ________________________", styles["body"])],
    ]
    sign_table = Table(sign_data, colWidths=[80 * mm, 80 * mm])
    sign_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(sign_table)

    doc.build(story)
    return path


def generate_contract_pdf(settings: Settings, booking: Any | None = None, dates: list[str] | None = None) -> Path:
    if booking:
        filename = f"contract_booking_{booking['id']}.pdf"
    else:
        filename = "rental_contract_template.pdf"
    return _build_pdf(GENERATED_DIR / filename, settings=settings, booking=booking, dates=dates)

def get_contract_pdf(settings: Settings, booking: Any | None = None, dates: list[str] | None = None) -> Path:
    """Возвращает PDF договора.

    Если в docs/rental_agreement.pdf лежит ваш статичный договор, бот отправляет именно его.
    Если файла нет, бот использует старую динамическую генерацию PDF.
    """
    if STATIC_CONTRACT_PATH.exists():
        return STATIC_CONTRACT_PATH
    return generate_contract_pdf(settings, booking=booking, dates=dates)

