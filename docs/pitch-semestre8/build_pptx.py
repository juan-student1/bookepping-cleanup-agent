"""Pitch editable del decálogo. Mismos 10 cuadros que el PDF."""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

W, H = Inches(13.333), Inches(7.5)
BG = RGBColor(0x07, 0x14, 0x10)
CARD = RGBColor(0x10, 0x24, 0x1C)
CREAM = RGBColor(0xF4, 0xEC, 0xDF)
GOLD = RGBColor(0xD4, 0xB4, 0x83)
MUTED = RGBColor(0xD9, 0xD0, 0xC2)
SERIF = "Georgia"
SANS = "Calibri"


def set_run(run, text, size, color, font, bold=False):
    run.text = text
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.name = font
    run.font.bold = bold
    run.font.italic = False


def add_text(slide, l, t, w, h, lines, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(l, t, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.margin_left = Emu(0)
    tf.margin_right = Emu(0)
    tf.margin_top = Emu(0)
    tf.margin_bottom = Emu(0)
    box.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    tf._txBody.bodyPr.set("anchor", {MSO_ANCHOR.TOP: "t", MSO_ANCHOR.MIDDLE: "ctr", MSO_ANCHOR.BOTTOM: "b"}[anchor])
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = line.get("align", PP_ALIGN.LEFT)
        p.space_before = Pt(line.get("before", 0))
        p.space_after = Pt(line.get("after", 0))
        run = p.add_run()
        set_run(run, line["text"], line.get("size", 18), line.get("color", CREAM), line.get("font", SANS), line.get("bold", False))
    return box


def rect(slide, l, t, w, h, fill, line=None):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, l, t, w, h)
    shape.adjustments[0] = 0.08
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill
    if line is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = line
        shape.line.width = Pt(1.25)
    # kill default shadow-looking line
    sp = shape._element
    style = sp.find(qn("p:style"))
    if style is not None:
        sp.remove(style)
    return shape


def bg(slide):
    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, W, H)
    shape.fill.solid()
    shape.fill.fore_color.rgb = BG
    shape.line.fill.background()
    sp = shape._element
    style = sp.find(qn("p:style"))
    if style is not None:
        sp.remove(style)
    # send to back
    sp_tree = slide.shapes._spTree
    sp_tree.remove(shape._element)
    sp_tree.insert(2, shape._element)


def kicker(slide, text, num):
    add_text(slide, Inches(0.7), Inches(0.38), Inches(8), Inches(0.32), [
        {"text": text.upper(), "size": 13, "color": GOLD, "bold": True, "font": SANS}
    ])
    add_text(slide, Inches(10.2), Inches(0.38), Inches(2.4), Inches(0.32), [
        {"text": num, "size": 13, "color": RGBColor(0xC9, 0xBF, 0xAE), "align": PP_ALIGN.RIGHT, "font": SANS}
    ])


def title(slide, text):
    add_text(slide, Inches(0.7), Inches(0.78), Inches(12), Inches(0.9), [
        {"text": text, "size": 36, "font": SERIF, "color": CREAM}
    ])


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def build():
    prs = Presentation()
    prs.slide_width = W
    prs.slide_height = H
    blank = prs.slide_layouts[6]

    # 1 cover
    s = prs.slides.add_slide(blank)
    bg(s)
    add_text(s, Inches(0.75), Inches(0.7), Inches(7.2), Inches(0.35), [
        {"text": "EXPOSICIÓN FINAL  ·  SEMESTRE 8", "size": 14, "color": GOLD, "bold": True}
    ])
    add_text(s, Inches(0.72), Inches(1.35), Inches(7.4), Inches(1.3), [
        {"text": "LedgerAI", "size": 72, "font": SERIF}
    ])
    add_text(s, Inches(0.75), Inches(2.85), Inches(7), Inches(1.3), [
        {"text": "Decálogo del estudio de mercado", "size": 28, "font": SERIF},
        {"text": "The Profit Catalyst", "size": 18, "color": GOLD, "before": 10},
    ])
    add_text(s, Inches(0.75), Inches(5.7), Inches(6), Inches(1.2), [
        {"text": "PRESENTAN", "size": 12, "color": GOLD, "bold": True},
        {"text": "Juan Esteban Gallego Loaiza", "size": 20, "before": 8},
        {"text": "Kevin Parra", "size": 20, "before": 2},
    ])
    add_text(s, Inches(6.2), Inches(5.55), Inches(1.8), Inches(1.3), [
        {"text": "5:00", "size": 40, "font": SERIF, "align": PP_ALIGN.RIGHT},
        {"text": "minutos", "size": 14, "color": GOLD, "align": PP_ALIGN.RIGHT, "before": 2},
    ])
    s.shapes.add_picture("ledgerai-hero-mark.png", Inches(8.15), Inches(1.35), Inches(4.5), Inches(4.5))
    notes(s, "0:00 Juan. Buenas. Somos Juan Esteban Gallego Loaiza y Kevin Parra, semestre 8. En cinco minutos, el decálogo de mercado de LedgerAI, el software de The Profit Catalyst para sanear contabilidad atrasada.")

    # 2 problem
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "Árbol de problemas  ·  ZOPP", "02  /  10")
    title(s, "Libros que no se pueden usar.")
    cards = [
        ("EFECTOS", "Sanciones fiscales\nPérdida de dinero\nDeudas por mala información financiera", False),
        ("PROBLEMA CENTRAL", "Libros contables desorganizados, atrasados o inestables.", True),
        ("CAUSAS", "Papel o Excel manual, sin software\nDesconocimiento fiscal\nSoporte documental incompleto", False),
    ]
    for i, (tag, body, core) in enumerate(cards):
        left = Inches(0.7 + i * 4.15)
        rect(s, left, Inches(2.05), Inches(3.95), Inches(4.15), CARD, GOLD if core else None)
        add_text(s, left + Inches(0.28), Inches(2.28), Inches(3.4), Inches(0.35), [
            {"text": tag, "size": 12, "color": GOLD, "bold": True}
        ])
        add_text(s, left + Inches(0.28), Inches(2.75), Inches(3.4), Inches(3.1), [
            {"text": body, "size": 20 if core else 18, "font": SERIF if core else SANS}
        ])
    add_text(s, Inches(0.7), Inches(6.5), Inches(6), Inches(0.4), [
        {"text": "Caso de trabajo real", "size": 16, "color": MUTED}
    ])
    add_text(s, Inches(7.2), Inches(6.5), Inches(5.4), Inches(0.4), [
        {"text": "My Xcell Network CORP  ·  Miami", "size": 16, "color": GOLD, "align": PP_ALIGN.RIGHT, "bold": True}
    ])
    notes(s, "0:20 El problema central del árbol ZOPP: libros desorganizados, atrasados o inestables. Arriba, sanciones, pérdida de dinero y deudas. Abajo, Excel o papel, desconocimiento fiscal y soportes incompletos. El caso real es My Xcell Network, en Miami.")

    # 3 product
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "1  ·  Qué es", "03  /  10")
    title(s, "Un SaaS para sanear lo atrasado.")
    steps = [
        ("01", "Lee", "Google Drive, PDF, Excel, CSV o foto. Un archivo a la vez."),
        ("02", "Clasifica", "Cada movimiento va al plan de cuentas. Ingreso solo si es un depósito real."),
        ("03", "Concilia", "Banco por mes y por cuenta, con las reglas del cliente."),
        ("04", "Entrega", "Balance, Pérdidas y Ganancias y Flujo de efectivo del periodo."),
    ]
    for i, (n, h, body) in enumerate(steps):
        top = Inches(1.85 + i * 0.95)
        rect(s, Inches(0.55), top, Inches(4.55), Inches(0.88), CARD)
        add_text(s, Inches(0.7), top + Inches(0.12), Inches(0.55), Inches(0.6), [
            {"text": n, "size": 18, "font": SERIF, "color": GOLD}
        ])
        add_text(s, Inches(1.3), top + Inches(0.1), Inches(3.6), Inches(0.7), [
            {"text": h, "size": 16, "font": SERIF},
            {"text": body, "size": 11, "color": MUTED, "before": 2},
        ])
    add_text(s, Inches(0.55), Inches(5.75), Inches(4.55), Inches(0.9), [
        {"text": "El humano verifica. El CPA recibe el paquete.", "size": 14, "font": SERIF},
        {"text": "No es outsourcing · No es escritorio · Sin IA de pago", "size": 12, "color": GOLD, "before": 6},
    ])
    s.shapes.add_picture("shots/landing.png", Inches(5.3), Inches(1.85), Inches(7.45), Inches(4.55))
    add_text(s, Inches(5.3), Inches(6.5), Inches(7.45), Inches(0.35), [
        {"text": "Producto en vivo  ·  ledgerai-0wyy.onrender.com", "size": 12, "color": MUTED}
    ])
    notes(s, "0:55 LedgerAI es un servicio digital. Esta es la pantalla real, en el navegador. Lee lo que el cliente ya tiene, clasifica en su plan de cuentas, concilia banco por mes y entrega Balance, Pérdidas y Ganancias y Flujo de efectivo. El dueño verifica. El CPA recibe el paquete.")

    # 4 demand
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "2  ·  Demanda real", "04  /  10")
    title(s, "Quién compra.")
    add_text(s, Inches(0.7), Inches(1.9), Inches(7.2), Inches(2.2), [
        {"text": "El dueño del negocio.", "size": 36, "font": SERIF},
        {"text": "No el público.", "size": 36, "font": SERIF, "color": GOLD, "before": 4},
    ])
    add_text(s, Inches(0.7), Inches(4.3), Inches(7.0), Inches(1.3), [
        {"text": "Ya es cliente de The Profit Catalyst. Tiene extractos de varios años sin ordenar y debe entregarle un paquete claro a su CPA.", "size": 18, "color": MUTED}
    ])
    rect(s, Inches(8.15), Inches(1.95), Inches(4.45), Inches(3.55), CARD, GOLD)
    add_text(s, Inches(8.4), Inches(2.15), Inches(4.0), Inches(3.15), [
        {"text": "El CPA recibe", "size": 20, "font": SERIF},
        {"text": "No es el comprador. Recibe los estados, listos para revisar.", "size": 15, "color": MUTED, "before": 6},
        {"text": "Población objetivo", "size": 20, "font": SERIF, "before": 16},
        {"text": "Cartera activa de TPC con libros desorganizados, atrasados o inestables.", "size": 15, "color": MUTED, "before": 6},
    ])
    rect(s, Inches(0.7), Inches(5.9), Inches(11.9), Inches(0.95), CARD, GOLD)
    add_text(s, Inches(0.95), Inches(6.1), Inches(11.4), Inches(0.6), [
        {"text": "Cuantificación honesta: un cliente real, My Xcell. El censo de toda la cartera no se inventa.", "size": 18}
    ])
    notes(s, "1:35 Kevin. El cliente es el dueño que ya contrata a TPC. El contador no compra: recibe el resultado. Hoy lo demostramos con My Xcell. No inventamos el número de empresas de la cartera.")

    # 5 competition
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "3  ·  Oferta y competencia", "05  /  10")
    title(s, "El mismo problema, otro oficio.")
    headers = ["Oferta", "Qué cubre", "Precio que sí se sabe", "Límite"]
    rows = [
        ["Papel o Excel", "El dueño arma los libros", "El tiempo de la persona", "Se ahoga con años de extractos"],
        ["QuickBooks", "Contabilidad del día a día", "Licencia de pago", "Pesado si solo hay que limpiar"],
        ["Bookkeeping humano", "Alguien clasifica línea a línea", "Por hora o por mes", "Limitado por esas horas"],
        ["IA de pago", "Clasifica con un modelo alquilado", "Software más el modelo", "Costo variable"],
        ["LedgerAI", "Limpieza de atrasados para clientes TPC", "Suscripción por acordar", "Reglas del cliente, sin modelo de pago"],
    ]
    xs = [0.7, 3.3, 7.15, 10.15]
    ws = [2.5, 3.7, 2.9, 2.5]
    for x, w, htxt in zip(xs, ws, headers):
        add_text(s, Inches(x), Inches(1.95), Inches(w), Inches(0.35), [
            {"text": htxt.upper(), "size": 11, "color": GOLD, "bold": True}
        ])
    for r, row in enumerate(rows):
        top = Inches(2.4 + r * 0.9)
        if r == len(rows) - 1:
            rect(s, Inches(0.55), top - Inches(0.08), Inches(12.2), Inches(0.82), RGBColor(0x1A, 0x30, 0x24), GOLD)
        for x, w, cell in zip(xs, ws, row):
            add_text(s, Inches(x), top, Inches(w), Inches(0.7), [
                {"text": cell, "size": 15, "bold": r == len(rows) - 1}
            ])
    notes(s, "2:10 La misma necesidad la cubren Excel, QuickBooks, el bookkeeper por hora y las herramientas que alquilan un modelo. No contamos cuántas empresas iguales hay en el país. Nuestro lugar es limpiar lo atrasado, con las reglas del cliente, sin pagar un modelo por cada línea.")

    # 6 price
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "4  ·  Precio", "06  /  10")
    title(s, "Sin tarifa inventada.")
    prices = [
        ("HISTÓRICO", "No hay lista cobrada.", "LedgerAI todavía no tiene una tarifa anterior que citar.", False),
        ("PROPUESTO", "Suscripción mensual por cliente.", "El monto en dólares se acuerda con TPC. No se fija en este estudio.", True),
        ("JUSTIFICACIÓN", "Las horas que ya paga.", "Se compara con Excel o bookkeeping de ese cliente. El prototipo no alquila un modelo.", False),
    ]
    for i, (tag, h, body, mid) in enumerate(prices):
        left = Inches(0.7 + i * 4.15)
        rect(s, left, Inches(2.05), Inches(3.95), Inches(4.55), CARD, GOLD if mid else None)
        add_text(s, left + Inches(0.28), Inches(2.3), Inches(3.4), Inches(3.9), [
            {"text": tag, "size": 13, "color": GOLD, "bold": True},
            {"text": h, "size": 26, "font": SERIF, "before": 14},
            {"text": body, "size": 16, "color": MUTED, "before": 12},
        ])
    notes(s, "2:50 Juan. No hay precio histórico. Lo propuesto es suscripción mensual. El monto no se fija hasta acordarlo con TPC. Se compara contra las horas que ese cliente ya paga.")

    # 7 channel
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "5 y 6  ·  Canal y marketing", "07  /  10")
    title(s, "De quien lo hace a quien lo usa.")
    nodes = [
        ("01", "Freelancer", "Relación TPC"),
        ("02", "Navegador", "PC o celular"),
        ("03", "Extractos", "Drive o archivo"),
        ("04", "Paquete", "Para el CPA"),
        ("05", "Sin tienda", "Sin instalador"),
    ]
    for i, (n, h, body) in enumerate(nodes):
        left = Inches(0.55 + i * 2.55)
        rect(s, left, Inches(1.8), Inches(2.4), Inches(1.05), CARD)
        add_text(s, left + Inches(0.14), Inches(1.88), Inches(2.15), Inches(0.9), [
            {"text": f"{n}  {h}", "size": 13, "font": SERIF, "color": GOLD},
            {"text": body, "size": 12, "color": MUTED, "before": 4},
        ])
    s.shapes.add_picture("shots/landing.png", Inches(0.55), Inches(3.05), Inches(6.2), Inches(2.95))
    s.shapes.add_picture("shots/landing-mobile.png", Inches(6.9), Inches(3.05), Inches(1.35), Inches(2.95))
    s.shapes.add_picture("shots/login.png", Inches(8.45), Inches(3.05), Inches(4.3), Inches(2.95))
    rect(s, Inches(0.55), Inches(6.2), Inches(12.2), Inches(0.95), CARD, GOLD)
    add_text(s, Inches(0.75), Inches(6.35), Inches(1.6), Inches(0.7), [
        {"text": "$0", "size": 28, "font": SERIF, "color": GOLD},
    ])
    add_text(s, Inches(2.4), Inches(6.42), Inches(10.0), Inches(0.6), [
        {"text": "No hay pauta. La promoción es la demo con un cliente real, dentro de TPC.", "size": 16}
    ])
    notes(s, "3:20 El freelancer entra por la relación de TPC. El cliente abre el navegador, en computador o celular, con su usuario. Estas son pantallas reales. Extractos por Drive o archivo. Presupuesto de promoción: cero.")

    # 8 geo
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "7 y 8  ·  Insumos y geografía", "08  /  10")
    title(s, "Con qué se sostiene, y dónde.")
    supplies = [
        ("Extractos", "Google Drive, compartido por el cliente."),
        ("Lectura y reglas", "Programas libres. Sin proveedor de IA de pago."),
        ("Aplicación", "Hosting gratuito. Puede dormirse y tiene tope de memoria."),
    ]
    for i, (h, body) in enumerate(supplies):
        top = Inches(2.05 + i * 1.15)
        rect(s, Inches(0.7), top, Inches(6.7), Inches(1.02), CARD)
        add_text(s, Inches(0.92), top + Inches(0.18), Inches(6.3), Inches(0.7), [
            {"text": h, "size": 16, "bold": True},
            {"text": body, "size": 14, "color": MUTED, "before": 2},
        ])
    add_text(s, Inches(0.7), Inches(5.6), Inches(6.7), Inches(1.2), [
        {"text": "Cuello de botella. Que el cliente entregue las carpetas completas y que alguien verifique lo clasificado.", "size": 16}
    ])
    rect(s, Inches(7.7), Inches(2.05), Inches(4.9), Inches(4.55), CARD, GOLD)
    add_text(s, Inches(8.0), Inches(2.3), Inches(4.4), Inches(4.0), [
        {"text": "MERCADO INICIAL", "size": 13, "color": GOLD, "bold": True},
        {"text": "Miami", "size": 48, "font": SERIF, "before": 8},
        {"text": "Florida, Estados Unidos. Ahí están los clientes TPC de esta cartera. El uso es digital.", "size": 16, "color": MUTED, "before": 8},
        {"text": "No se afirma un mercado nacional hasta que la cartera salga de esa zona.", "size": 16, "before": 16},
    ])
    notes(s, "3:50 Kevin. Insumos digitales: Drive, programas libres y un hosting que puede dormirse. El cuello de botella es la carpeta completa y la verificación. Mercado inicial: Miami, Florida. No afirmamos un mercado nacional.")

    # 9 formula
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "9  ·  Proyección de ventas", "09  /  10")
    title(s, "La demanda, en fórmula.")
    boxes = [
        ("UNIDAD", "Clientes TPC con libros atrasados", "Cifra abierta. El censo no está en el estudio."),
        ("PRECIO", "Suscripción mensual acordada", "Cifra abierta. Se cierra con TPC."),
        ("VENTAS", "Sin dólares inventados", "My Xcell prueba uso. No prueba el tamaño del mercado."),
    ]
    for i, (tag, h, body) in enumerate(boxes):
        left = Inches(0.7 + i * 4.15)
        rect(s, left, Inches(2.35), Inches(3.35), Inches(3.15), CARD, GOLD if i == 2 else None)
        add_text(s, left + Inches(0.25), Inches(2.55), Inches(2.9), Inches(2.7), [
            {"text": tag, "size": 12, "color": GOLD, "bold": True},
            {"text": h, "size": 22, "font": SERIF, "before": 10},
            {"text": body, "size": 14, "color": MUTED, "before": 10},
        ])
        if i < 2:
            add_text(s, left + Inches(3.3), Inches(3.3), Inches(0.8), Inches(0.8), [
                {"text": "×" if i == 0 else "=", "size": 36, "font": SERIF, "color": GOLD, "align": PP_ALIGN.CENTER}
            ])
    add_text(s, Inches(0.7), Inches(6.0), Inches(12), Inches(0.8), [
        {"text": "El primer caso demuestra el servicio. No proyecta una cartera que todavía no está contada.", "size": 18}
    ])
    notes(s, "4:20 La fórmula es clientes TPC con libros atrasados por la suscripción acordada. No se convierte en dólares: faltan el censo y el precio. My Xcell prueba uso, no el mercado entero.")

    # 10 close
    s = prs.slides.add_slide(blank)
    bg(s)
    kicker(s, "10  ·  Conclusiones y riesgos", "10  /  10")
    add_text(s, Inches(0.7), Inches(1.15), Inches(6.3), Inches(2.4), [
        {"text": "Demanda conocida. Precio abierto a propósito.", "size": 32, "font": SERIF}
    ])
    add_text(s, Inches(0.7), Inches(3.7), Inches(6.2), Inches(1.6), [
        {"text": "Clientes de TPC con libros atrasados. Diferencia frente a Excel, QuickBooks completo y la IA de pago. Canal digital y directo.", "size": 16, "color": MUTED}
    ])
    risks = [
        "Sin precio cerrado no hay ingreso predecible.",
        "La cartera puede ser pequeña. Un caso no es el mercado.",
        "El hosting gratuito se duerme y limita el volumen.",
        "Si el extracto se lee mal, alguien corrige la cuenta.",
        "El reporte apoya al CPA. No evita la sanción por sí solo.",
    ]
    for i, risk in enumerate(risks):
        top = Inches(1.2 + i * 0.85)
        rect(s, Inches(7.2), top, Inches(5.45), Inches(0.75), CARD)
        add_text(s, Inches(7.4), top + Inches(0.16), Inches(5.05), Inches(0.48), [
            {"text": f"0{i+1}   {risk}", "size": 14}
        ])
    add_text(s, Inches(0.7), Inches(5.85), Inches(5), Inches(0.9), [
        {"text": "Gracias.", "size": 40, "font": SERIF}
    ])
    add_text(s, Inches(7.2), Inches(6.0), Inches(5.4), Inches(1.0), [
        {"text": "Juan Esteban Gallego Loaiza", "size": 16, "align": PP_ALIGN.RIGHT},
        {"text": "Kevin Parra  ·  Semestre 8", "size": 16, "align": PP_ALIGN.RIGHT, "before": 2},
    ])
    notes(s, "4:40 Kevin cierra. Demanda acotada y conocida. Nos diferenciamos de Excel, de QuickBooks completo y de la IA de pago. Canal digital y directo. Precio y tamaño abiertos a propósito. Recorre los cinco riesgos y cierra con gracias.")

    prs.save("LedgerAI-decalogo.pptx")


if __name__ == "__main__":
    build()
