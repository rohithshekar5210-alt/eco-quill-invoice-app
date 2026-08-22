import os
import re
import csv
import json
import smtplib
import urllib.parse
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path

import streamlit as st
from num2words import num2words
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# =========================================================
# APP CONFIG
# =========================================================

st.set_page_config(
    page_title="Custom Invoice Generator", page_icon="🧾", layout="wide"
)

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
if not ASSETS_DIR.exists():
    ASSETS_DIR.mkdir(parents=True)

SETTINGS_FILE = BASE_DIR / "business_settings.json"
LOGO_PATH = ASSETS_DIR / "business_logo.png"
SIGNATURE_PATH = ASSETS_DIR / "digital_signature.png"

INVOICE_DIR = BASE_DIR / "invoices"
if not INVOICE_DIR.exists():
    INVOICE_DIR.mkdir(parents=True)
HISTORY_FILE = INVOICE_DIR / "invoice_history.csv"


# =========================================================
# PREMIUM COLOR PALETTE
# =========================================================

COLOR_PRIMARY_DARK = "#0B3D2E"
COLOR_PRIMARY = "#145A32"
COLOR_ACCENT_GOLD = "#B8860B"
COLOR_ACCENT_GOLD_LIGHT = "#F4E9D0"
COLOR_TEXT = "#1C2833"
COLOR_MUTED = "#5D6D64"
COLOR_BORDER = "#D8E0D8"
COLOR_ROW_TINT = "#F5F9F5"


# =========================================================
# DEFAULT CUSTOMIZABLE SETTINGS
# =========================================================

DEFAULT_SETTINGS = {
    "company_name": "EcoQuill",
    "company_tagline": "Sustainability Starts With Every Bag",
    "company_address": "660, 9th Cross, Weavers Colony, Gottigere Post, Bannerghatta Road, Bangalore - 560083",
    "company_phone": "+91 7899334559",
    "company_email": "ecoquill.biobags@gmail.com",
    "company_gstin": "AB290726105417Z",
    "invoice_title": "TAX INVOICE",
    "invoice_prefix": "EQ",
    "default_place_of_supply": "Karnataka",
    "bank_name": "Bank Name Placeholder",
    "account_name": "EcoQuill",
    "account_no": "Account Number Placeholder",
    "ifsc_code": "IFSC Placeholder",
    "upi_id": "UPI Placeholder",
    "terms_conditions": (
        "Goods once sold will not be taken back.\n"
        "Payment should be made as per agreed terms.\n"
        "Any dispute is subject to Bangalore jurisdiction only.\n"
        "Please verify quantity and product details at the time of delivery.\n"
        "This is a computer-generated invoice."
    ),
    "email_subject_template": "{company_name} Invoice {invoice_no}",
    "email_message_template": (
        "Dear {customer_name},\n\n"
        "Please find attached your invoice from {company_name}.\n\n"
        "Invoice No: {invoice_no}\n"
        "Invoice Date: {invoice_date}\n"
        "Grand Total: {grand_total}\n\n"
        "Thank you for choosing {company_name}.\n\n"
        "Regards,\n{company_name}"
    ),
    "whatsapp_message_template": (
        "Hello {customer_name},\n\n"
        "Your invoice from {company_name} is ready.\n"
        "Invoice No: {invoice_no}\n"
        "Grand Total: {grand_total}\n\n"
        "Please check your email for the PDF invoice.\n\n"
        "Thank you,\n{company_name}"
    ),
}


# =========================================================
# SETTINGS FUNCTIONS
# =========================================================


def load_settings():
    settings = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                saved_settings = json.load(file)
            settings.update(saved_settings)
        except Exception:
            pass
    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(settings, file, indent=4, ensure_ascii=False)


def save_uploaded_image(uploaded_file, destination):
    if uploaded_file is not None:
        with open(destination, "wb") as file:
            file.write(uploaded_file.getbuffer())


settings = load_settings()


# =========================================================
# UNICODE FONT REGISTRATION
# =========================================================


def register_invoice_fonts():
    possible_regular_fonts = [
        ASSETS_DIR / "segoeui.ttf",
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    possible_bold_fonts = [
        ASSETS_DIR / "segoeuib.ttf",
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]

    regular_path = next((p for p in possible_regular_fonts if p.exists()), None)
    bold_path = next((p for p in possible_bold_fonts if p.exists()), None)

    if regular_path and bold_path:
        pdfmetrics.registerFont(TTFont("InvoiceRegular", str(regular_path)))
        pdfmetrics.registerFont(TTFont("InvoiceBold", str(bold_path)))
        return "InvoiceRegular", "InvoiceBold"

    return "Helvetica", "Helvetica-Bold"


FONT_REGULAR, FONT_BOLD = register_invoice_fonts()


# =========================================================
# BASIC FUNCTIONS
# =========================================================


def clean_phone_number(phone):
    if not phone:
        return ""
    return re.sub(r"\D", "", phone)


def format_inr(amount):
    try:
        return f"₹ {amount:,.2f}"
    except Exception:
        return f"₹ {amount}"


def amount_to_words(amount):
    try:
        rupees = int(round(amount))
        words = num2words(rupees, lang="en_IN").title()
        return f"{words} Rupees Only"
    except Exception:
        return "Amount In Words Not Available"


def safe_filename(text):
    text = re.sub(r"[^A-Za-z0-9_-]", "_", str(text))
    return text[:80]


def escape_pdf_text(value):
    value = "" if value is None else str(value)
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def render_template(template, **values):
    try:
        return template.format(**values)
    except Exception:
        return template


def save_invoice_history(invoice_data):
    file_exists = HISTORY_FILE.exists()
    fieldnames = [
        "created_on", "invoice_no", "invoice_date", "customer_name",
        "customer_phone", "customer_email", "taxable_value", "gst_amount",
        "packing_charges", "grand_total", "pdf_file"
    ]

    with open(HISTORY_FILE, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(invoice_data)


# =========================================================
# PDF GENERATION
# =========================================================


def generate_invoice_pdf(
    company_details,
    customer_details,
    invoice_details,
    product_rows,
    totals,
    bank_details,
    terms_conditions,
):
    invoice_no_file = safe_filename(invoice_details["invoice_no"])
    customer_file = safe_filename(customer_details["name"])
    company_file = safe_filename(company_details["name"])
    pdf_filename = f"{company_file}_Invoice_{invoice_no_file}_{customer_file}.pdf"
    pdf_path = INVOICE_DIR / pdf_filename

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()
    style_title = ParagraphStyle(
        "TitleStyle", parent=styles["Title"], fontName=FONT_BOLD,
        fontSize=24, textColor=colors.HexColor(COLOR_PRIMARY_DARK),
        alignment=TA_LEFT, spaceAfter=2,
    )
    style_subtitle = ParagraphStyle(
        "SubtitleStyle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=9, textColor=colors.HexColor(COLOR_MUTED),
        alignment=TA_LEFT, leading=12,
    )
    style_heading = ParagraphStyle(
        "HeadingStyle", parent=styles["Heading2"], fontName=FONT_BOLD,
        fontSize=10, textColor=colors.HexColor(COLOR_PRIMARY_DARK), spaceAfter=6,
    )
    style_normal = ParagraphStyle(
        "NormalStyle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=9, leading=12, textColor=colors.HexColor(COLOR_TEXT),
    )
    style_normal_bold = ParagraphStyle(
        "NormalBoldStyle", parent=style_normal, fontName=FONT_BOLD,
    )
    style_small = ParagraphStyle(
        "SmallStyle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=8, leading=10, textColor=colors.HexColor(COLOR_MUTED),
    )
    style_right = ParagraphStyle(
        "RightStyle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=9, leading=12, alignment=TA_RIGHT,
    )
    style_table_cell = ParagraphStyle(
        "TableCellStyle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=8, leading=11, textColor=colors.HexColor(COLOR_TEXT),
    )
    style_table_cell_right = ParagraphStyle(
        "TableCellRightStyle", parent=style_table_cell, alignment=TA_RIGHT,
    )
    style_table_cell_center = ParagraphStyle(
        "TableCellCenterStyle", parent=style_table_cell, alignment=TA_CENTER,
    )

    story = []

    company_block = [
        Paragraph(escape_pdf_text(company_details["name"]), style_title),
        Paragraph(escape_pdf_text(company_details["tagline"]), style_subtitle),
        Paragraph(escape_pdf_text(company_details["address"]), style_subtitle),
        Paragraph(
            f"Phone: {escape_pdf_text(company_details['phone'])}  |  "
            f"Email: {escape_pdf_text(company_details['email'])}",
            style_subtitle,
        ),
        Paragraph(f"GSTIN: {escape_pdf_text(company_details['gstin'])}", style_subtitle),
    ]

    if LOGO_PATH.exists():
        try:
            logo_flowable = Image(str(LOGO_PATH), width=24 * mm, height=15.2 * mm)
            header_table = Table([[logo_flowable, company_block]], colWidths=[26 * mm, 154 * mm])
            header_table.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(header_table)
        except Exception:
            story.extend(company_block)
    else:
        story.extend(company_block)

    story.append(Spacer(1, 8))
    story.append(HRFlowable(
        width="100%", thickness=1.4, color=colors.HexColor(COLOR_ACCENT_GOLD)
    ))
    story.append(Spacer(1, 8))

    invoice_title_style = ParagraphStyle(
        "InvoiceTitle", parent=styles["Normal"], fontName=FONT_BOLD,
        fontSize=14, textColor=colors.white, alignment=TA_CENTER,
    )
    title_table = Table(
        [[Paragraph(f"<b>{escape_pdf_text(invoice_details['invoice_title'])}</b>", invoice_title_style)]],
        colWidths=[180 * mm],
    )
    title_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLOR_PRIMARY_DARK)),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(COLOR_ACCENT_GOLD)),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.append(title_table)
    story.append(Spacer(1, 10))

    billed_to = [
        Paragraph("Billed To", style_heading),
        Paragraph(f"<b>Name:</b> {escape_pdf_text(customer_details['name'])}", style_normal),
        Paragraph(f"<b>Address:</b> {escape_pdf_text(customer_details['address'])}", style_normal),
        Paragraph(f"<b>Phone:</b> {escape_pdf_text(customer_details['phone'])}", style_normal),
        Paragraph(f"<b>WhatsApp:</b> {escape_pdf_text(customer_details['whatsapp'])}", style_normal),
        Paragraph(f"<b>Email:</b> {escape_pdf_text(customer_details['email'] or 'Not provided')}", style_normal),
        Paragraph(f"<b>Customer GSTIN:</b> {escape_pdf_text(customer_details['gstin'] or 'Not provided')}", style_normal),
    ]
    invoice_info = [
        Paragraph("Invoice Details", style_heading),
        Paragraph(f"<b>Invoice No:</b> {escape_pdf_text(invoice_details['invoice_no'])}", style_normal),
        Paragraph(f"<b>Invoice Date:</b> {escape_pdf_text(invoice_details['invoice_date'])}", style_normal),
        Paragraph(f"<b>Place of Supply:</b> {escape_pdf_text(invoice_details['place_of_supply'])}", style_normal),
        Paragraph(f"<b>Payment Status:</b> {escape_pdf_text(invoice_details['payment_status'])}", style_normal),
    ]

    info_table = Table([[billed_to, invoice_info]], colWidths=[90 * mm, 90 * mm])
    info_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(COLOR_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FCF9")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(info_table)
    story.append(Spacer(1, 12))

    data = [["Sr.", "Description of Goods", "HSN/SAC", "Qty", "Rate", "GST %", "Amount"]]
    for index, row in enumerate(product_rows, start=1):
        data.append([
            Paragraph(str(index), style_table_cell_center),
            Paragraph(escape_pdf_text(row["product_name"]), style_table_cell),
            Paragraph(escape_pdf_text(row["hsn"]), style_table_cell_center),
            Paragraph(f"{row['quantity']:,.2f}", style_table_cell_center),
            Paragraph(format_inr(row["rate"]), style_table_cell_right),
            Paragraph(f"{row['gst_percent']:,.2f}%", style_table_cell_center),
            Paragraph(format_inr(row["line_amount"]), style_table_cell_right),
        ])

    product_table = Table(
        data,
        colWidths=[12 * mm, 59 * mm, 22 * mm, 18 * mm, 26 * mm, 18 * mm, 25 * mm],
        repeatRows=1,
    )
    product_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_PRIMARY_DARK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(COLOR_ROW_TINT)]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(product_table)
    story.append(Spacer(1, 12))

    amount_words_table = Table([
        [Paragraph("<b>Bill Amount In Words:</b>", style_normal),
         Paragraph(escape_pdf_text(amount_to_words(totals["grand_total"])), style_normal)]
    ], colWidths=[45 * mm, 135 * mm])
    amount_words_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDFEFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(amount_words_table)
    story.append(Spacer(1, 8))

    totals_data = [
        [Paragraph("Taxable Value", style_normal), Paragraph(format_inr(totals["taxable_value"]), style_table_cell_right)],
        [Paragraph("Packing / Delivery Charges", style_normal), Paragraph(format_inr(totals["packing_charges"]), style_table_cell_right)],
        [Paragraph("GST Amount", style_normal), Paragraph(format_inr(totals["gst_amount"]), style_table_cell_right)],
        [Paragraph("<b>Grand Total</b>", style_normal_bold),
         Paragraph(f"<b>{format_inr(totals['grand_total'])}</b>", ParagraphStyle(
             "GrandTotalRight", parent=style_table_cell_right, fontName=FONT_BOLD, fontSize=10
         ))],
    ]
    totals_table = Table(totals_data, colWidths=[125 * mm, 55 * mm])
    totals_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(COLOR_ACCENT_GOLD_LIGHT)),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor(COLOR_ACCENT_GOLD)),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(totals_table)
    story.append(Spacer(1, 12))

    bank_text = (
        f"<b>Bank Details</b><br/>"
        f"Bank Name: {escape_pdf_text(bank_details['bank_name'])}<br/>"
        f"Account Name: {escape_pdf_text(bank_details['account_name'])}<br/>"
        f"Account No: {escape_pdf_text(bank_details['account_no'])}<br/>"
        f"IFSC Code: {escape_pdf_text(bank_details['ifsc'])}<br/>"
        f"UPI ID: {escape_pdf_text(bank_details['upi'])}"
    )
    terms_text = "<b>Terms &amp; Conditions</b><br/>" + "<br/>".join(
        [f"{i + 1}. {escape_pdf_text(term)}" for i, term in enumerate(terms_conditions)]
    )
    bottom_table = Table(
        [[Paragraph(bank_text, style_small), Paragraph(terms_text, style_small)]],
        colWidths=[90 * mm, 90 * mm],
    )
    bottom_table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFC")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(bottom_table)
    story.append(Spacer(1, 14))

    signature_content = []
    if SIGNATURE_PATH.exists():
        try:
            signature_content.append(Image(str(SIGNATURE_PATH), width=32 * mm, height=16 * mm))
        except Exception:
            pass
    signature_content.append(Paragraph(
        f"<b>For {escape_pdf_text(company_details['name'])}</b><br/>Authorised Signatory",
        style_right,
    ))

    signature_table = Table([["", signature_content]], colWidths=[90 * mm, 90 * mm])
    signature_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(signature_table)

    doc.build(story)
    return pdf_path


# =========================================================
# EMAIL AND WHATSAPP FUNCTIONS
# =========================================================


def send_invoice_email(sender_email, sender_password, recipients, subject, body, attachment_path):
    if not sender_email or not sender_password:
        return False, "Email sender ID or app password is missing."

    recipients = [email.strip() for email in recipients if email and email.strip()]
    if not recipients:
        return False, "No recipient email address provided."

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = ", ".join(recipients)
        msg.set_content(body)

        with open(attachment_path, "rb") as file:
            msg.add_attachment(
                file.read(), maintype="application", subtype="pdf",
                filename=os.path.basename(attachment_path),
            )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)

        return True, "Email sent successfully."
    except Exception as error:
        return False, str(error)


def generate_whatsapp_link(customer_whatsapp, message):
    clean_number = clean_phone_number(customer_whatsapp)
    if not clean_number:
        return ""
    if len(clean_number) == 10:
        clean_number = "91" + clean_number
    encoded_message = urllib.parse.quote(message)
    return f"https://wa.me/{clean_number}?text={encoded_message}"


# =========================================================
# PREMIUM CSS
# =========================================================

st.markdown(f"""
<style>
.main {{ background-color: #F7FAF7; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 2rem; }}
.hero-card {{
    padding: 26px 28px; border-radius: 18px;
    background: linear-gradient(135deg, {COLOR_PRIMARY_DARK} 0%, {COLOR_PRIMARY} 55%, #1E7A4A 100%);
    color: white; box-shadow: 0 8px 24px rgba(11, 61, 46, 0.22);
    margin-bottom: 20px; border-bottom: 3px solid {COLOR_ACCENT_GOLD};
}}
.hero-title {{ font-size: 34px; font-weight: 800; margin-bottom: 4px; letter-spacing: 0.3px; }}
.hero-subtitle {{ font-size: 15px; opacity: 0.95; }}
.section-card {{
    padding: 20px; border-radius: 16px; background-color: white;
    border: 1px solid #E5E8E8; border-top: 3px solid {COLOR_ACCENT_GOLD};
    box-shadow: 0 4px 16px rgba(0,0,0,0.04); margin-bottom: 16px;
}}
.success-box {{
    padding: 14px; border-radius: 12px; background-color: {COLOR_ACCENT_GOLD_LIGHT};
    border-left: 5px solid {COLOR_ACCENT_GOLD}; color: {COLOR_PRIMARY_DARK}; font-weight: 600;
}}
div.stButton > button:first-child {{
    background-color: {COLOR_PRIMARY_DARK}; color: white; border-radius: 10px;
    border: 1px solid {COLOR_ACCENT_GOLD}; padding: 0.6rem 1rem; font-weight: 700;
}}
div.stButton > button:first-child:hover {{
    background-color: {COLOR_PRIMARY}; color: white; border-color: {COLOR_ACCENT_GOLD};
}}
</style>
""", unsafe_allow_html=True)


# =========================================================
# SIDEBAR CUSTOM TEMPLATE SETTINGS
# =========================================================

with st.sidebar:
    st.header("Template Settings")
    st.caption("Edit once and click Save. The details remain saved for future invoices.")

    with st.expander("Business Details", expanded=True):
        custom_company_name = st.text_input("Business Name", value=settings["company_name"])
        custom_company_tagline = st.text_input("Tagline", value=settings["company_tagline"])
        custom_company_address = st.text_area("Business Address", value=settings["company_address"])
        custom_company_phone = st.text_input("Business Phone", value=settings["company_phone"])
        custom_company_email = st.text_input("Business Email", value=settings["company_email"])
        custom_company_gstin = st.text_input("GSTIN / Tax Number", value=settings["company_gstin"])

    with st.expander("Invoice Defaults"):
        custom_invoice_title = st.text_input("Invoice Heading", value=settings["invoice_title"])
        custom_invoice_prefix = st.text_input("Invoice Number Prefix", value=settings["invoice_prefix"])
        custom_place_of_supply = st.text_input("Default Place of Supply", value=settings["default_place_of_supply"])

    with st.expander("Bank Details"):
        custom_bank_name = st.text_input("Bank Name", value=settings["bank_name"])
        custom_account_name = st.text_input("Account Name", value=settings["account_name"])
        custom_account_no = st.text_input("Account Number", value=settings["account_no"])
        custom_ifsc_code = st.text_input("IFSC Code", value=settings["ifsc_code"])
        custom_upi_id = st.text_input("UPI ID", value=settings["upi_id"])

    with st.expander("Terms and Conditions"):
        custom_terms = st.text_area(
            "Enter one term per line",
            value=settings["terms_conditions"],
            height=180,
        )

    with st.expander("Logo and Signature"):
        uploaded_logo = st.file_uploader("Upload Business Logo", type=["png", "jpg", "jpeg"])
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), caption="Current logo", width=140)
        uploaded_signature = st.file_uploader("Upload Signature Image", type=["png", "jpg", "jpeg"])
        if SIGNATURE_PATH.exists():
            st.image(str(SIGNATURE_PATH), caption="Current signature", width=140)
        st.caption("For best results, use a transparent PNG signature image.")

    with st.expander("Email and WhatsApp Templates"):
        custom_email_subject = st.text_input(
            "Email Subject", value=settings["email_subject_template"]
        )
        custom_email_message = st.text_area(
            "Email Message", value=settings["email_message_template"], height=240
        )
        custom_whatsapp_message = st.text_area(
            "WhatsApp Message", value=settings["whatsapp_message_template"], height=220
        )
        st.caption(
            "Available placeholders: {company_name}, {customer_name}, {invoice_no}, "
            "{invoice_date}, {grand_total}"
        )

    if st.button("Save Template Settings", use_container_width=True):
        updated_settings = {
            "company_name": custom_company_name,
            "company_tagline": custom_company_tagline,
            "company_address": custom_company_address,
            "company_phone": custom_company_phone,
            "company_email": custom_company_email,
            "company_gstin": custom_company_gstin,
            "invoice_title": custom_invoice_title,
            "invoice_prefix": custom_invoice_prefix,
            "default_place_of_supply": custom_place_of_supply,
            "bank_name": custom_bank_name,
            "account_name": custom_account_name,
            "account_no": custom_account_no,
            "ifsc_code": custom_ifsc_code,
            "upi_id": custom_upi_id,
            "terms_conditions": custom_terms,
            "email_subject_template": custom_email_subject,
            "email_message_template": custom_email_message,
            "whatsapp_message_template": custom_whatsapp_message,
        }
        save_settings(updated_settings)
        save_uploaded_image(uploaded_logo, LOGO_PATH)
        save_uploaded_image(uploaded_signature, SIGNATURE_PATH)
        st.success("Template settings saved permanently.")
        st.rerun()

    st.divider()
    st.subheader("Email Setup")
    sender_email = os.getenv("INVOICE_EMAIL_ID", os.getenv("ECOQUILL_EMAIL_ID", settings["company_email"]))
    sender_password = os.getenv("INVOICE_EMAIL_APP_PASSWORD", os.getenv("ECOQUILL_EMAIL_APP_PASSWORD", ""))
    if sender_password:
        st.success("Email app password found.")
    else:
        st.warning("Email password not found. PDF generation and WhatsApp sharing will still work.")


# =========================================================
# UI HEADER
# =========================================================

st.markdown(f"""
<div class="hero-card">
    <div class="hero-title">{escape_pdf_text(settings['company_name'])} Invoice Generator</div>
    <div class="hero-subtitle">Create professional GST-style PDF invoices using your saved business template.</div>
</div>
""", unsafe_allow_html=True)


# =========================================================
# MAIN FORM
# =========================================================

left_col, right_col = st.columns([1.1, 0.9])
with left_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Customer Details")
    customer_name = st.text_input("Customer Name", placeholder="Enter customer name")
    customer_address = st.text_area("Customer Address", placeholder="Enter customer full address")
    customer_phone = st.text_input("Customer Phone Number", placeholder="Example: 9876543210")
    customer_whatsapp = st.text_input("Customer WhatsApp Number", placeholder="Example: 9876543210")
    customer_email = st.text_input("Customer Email Address Optional", placeholder="customer@example.com")
    customer_gstin = st.text_input("Customer GSTIN Optional", placeholder="Enter GSTIN if available")
    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Invoice Details")
    default_invoice_no = f"{settings['invoice_prefix']}-{datetime.now().strftime('%Y%m%d-%H%M')}"
    invoice_no = st.text_input("Invoice Number", value=default_invoice_no)
    invoice_date = st.date_input("Invoice Date", value=date.today())
    place_of_supply = st.text_input("Place of Supply", value=settings["default_place_of_supply"])
    payment_status = st.selectbox("Payment Status", ["Pending", "Paid", "Partially Paid"])
    packing_charges = st.number_input(
        "Packing / Delivery Charges", min_value=0.0, value=0.0, step=10.0
    )
    st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# PRODUCT DETAILS
# =========================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Product Details")
number_of_items = st.number_input(
    "How many product rows?", min_value=1, max_value=20, value=1, step=1
)

product_rows = []
for i in range(int(number_of_items)):
    st.markdown(f"#### Product {i + 1}")
    col1, col2, col3, col4, col5 = st.columns([2.2, 1, 1, 1, 1])
    with col1:
        product_name = st.text_input(
            f"Product Name {i + 1}", value="BIO CARRY BAG", key=f"product_name_{i}"
        )
    with col2:
        hsn = st.text_input(f"HSN/SAC {i + 1}", value="39232990", key=f"hsn_{i}")
    with col3:
        quantity = st.number_input(
            f"Qty {i + 1}", min_value=0.0, value=1.0, step=1.0, key=f"quantity_{i}"
        )
    with col4:
        rate = st.number_input(
            f"Rate {i + 1}", min_value=0.0, value=0.0, step=1.0, key=f"rate_{i}"
        )
    with col5:
        gst_percent = st.number_input(
            f"GST % {i + 1}", min_value=0.0, max_value=100.0,
            value=5.0, step=0.5, key=f"gst_{i}"
        )

    line_amount = quantity * rate
    gst_amount_for_line = line_amount * gst_percent / 100
    product_rows.append({
        "product_name": product_name,
        "hsn": hsn,
        "quantity": quantity,
        "rate": rate,
        "gst_percent": gst_percent,
        "line_amount": line_amount,
        "gst_amount": gst_amount_for_line,
    })
st.markdown("</div>", unsafe_allow_html=True)


# =========================================================
# TOTAL CALCULATION
# =========================================================

taxable_value = sum(row["line_amount"] for row in product_rows)
gst_amount = sum(row["gst_amount"] for row in product_rows)
grand_total = taxable_value + gst_amount + packing_charges

metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
metric_col1.metric("Taxable Value", format_inr(taxable_value))
metric_col2.metric("GST Amount", format_inr(gst_amount))
metric_col3.metric("Packing / Delivery", format_inr(packing_charges))
metric_col4.metric("Grand Total", format_inr(grand_total))


# =========================================================
# GENERATE INVOICE
# =========================================================

company_details = {
    "name": settings["company_name"],
    "tagline": settings["company_tagline"],
    "address": settings["company_address"],
    "phone": settings["company_phone"],
    "email": settings["company_email"],
    "gstin": settings["company_gstin"],
}
bank_details = {
    "bank_name": settings["bank_name"],
    "account_name": settings["account_name"],
    "account_no": settings["account_no"],
    "ifsc": settings["ifsc_code"],
    "upi": settings["upi_id"],
}
terms_conditions = [
    term.strip() for term in settings["terms_conditions"].splitlines() if term.strip()
]

if st.button("Generate Invoice PDF and Send Email"):
    if not customer_name.strip():
        st.error("Please enter customer name.")
        st.stop()
    if not customer_address.strip():
        st.error("Please enter customer address.")
        st.stop()
    if taxable_value <= 0:
        st.error("Please enter product quantity and rate correctly.")
        st.stop()

    customer_details = {
        "name": customer_name,
        "address": customer_address,
        "phone": customer_phone,
        "whatsapp": customer_whatsapp,
        "email": customer_email,
        "gstin": customer_gstin,
    }
    invoice_details = {
        "invoice_title": settings["invoice_title"],
        "invoice_no": invoice_no,
        "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "place_of_supply": place_of_supply,
        "payment_status": payment_status,
    }
    totals = {
        "taxable_value": taxable_value,
        "gst_amount": gst_amount,
        "packing_charges": packing_charges,
        "grand_total": grand_total,
    }

    pdf_path = generate_invoice_pdf(
        company_details, customer_details, invoice_details,
        product_rows, totals, bank_details, terms_conditions
    )

    save_invoice_history({
        "created_on": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "invoice_no": invoice_no,
        "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "taxable_value": taxable_value,
        "gst_amount": gst_amount,
        "packing_charges": packing_charges,
        "grand_total": grand_total,
        "pdf_file": str(pdf_path),
    })

    st.markdown(
        f'<div class="success-box">Invoice PDF generated successfully: {pdf_path.name}</div>',
        unsafe_allow_html=True,
    )

    with open(pdf_path, "rb") as pdf_file:
        st.download_button(
            label="Download Invoice PDF", data=pdf_file.read(),
            file_name=pdf_path.name, mime="application/pdf"
        )

    template_values = {
        "company_name": settings["company_name"],
        "customer_name": customer_name,
        "invoice_no": invoice_no,
        "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "grand_total": format_inr(grand_total),
    }
    email_subject = render_template(settings["email_subject_template"], **template_values)
    email_body = render_template(settings["email_message_template"], **template_values)

    recipients = [settings["company_email"]]
    if customer_email.strip():
        recipients.append(customer_email.strip())

    if sender_password:
        email_success, email_message = send_invoice_email(
            sender_email, sender_password, recipients,
            email_subject, email_body, pdf_path
        )
        if email_success:
            st.success("Invoice email sent successfully.")
        else:
            st.warning(f"Invoice created, but email sending failed: {email_message}")
    else:
        st.warning("Invoice created. Email was not sent because the email app password is not set.")

    whatsapp_message = render_template(
        settings["whatsapp_message_template"], **template_values
    )
    whatsapp_link = generate_whatsapp_link(customer_whatsapp, whatsapp_message)
    if whatsapp_link:
        st.link_button("Share Invoice Details on WhatsApp", whatsapp_link)
    else:
        st.info("Enter a customer WhatsApp number to enable WhatsApp sharing.")


# =========================================================
# HISTORY SECTION
# =========================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Invoice History")
if HISTORY_FILE.exists():
    with open(HISTORY_FILE, mode="r", encoding="utf-8") as file:
        history_content = file.read()
    st.download_button(
        label="Download Invoice History CSV", data=history_content,
        file_name="invoice_history.csv", mime="text/csv"
    )
    st.caption("Invoice history is saved inside the invoices folder.")
else:
    st.caption("No invoice history found yet.")
st.markdown("</div>", unsafe_allow_html=True)

st.markdown("</div>", unsafe_allow_html=True)
{
     "version": "0.2.0",
     "configurations": [
       {
         "name": "Streamlit: EcoQuill App",
         "type": "debugpy",
         "request": "launch",
         "module": "streamlit",
         "args": ["run", "${workspaceFolder}/eco_quill_invoice_app/app.py"]
       }
     ]
   }

company_block = [
    Paragraph(
        escape_pdf_text(company_details["name"]),
        style_title,
    ),

    # One blank line after the company name
    Spacer(1, 5),

    Paragraph(
        escape_pdf_text(company_details["tagline"]),
        style_subtitle,
    ),
    Paragraph(
        escape_pdf_text(company_details["address"]),
        style_subtitle,
    ),
    Paragraph(
        f"Phone: {escape_pdf_text(company_details['phone'])}  |  "
        f"Email: {escape_pdf_text(company_details['email'])}",
        style_subtitle,
    ),
    Paragraph(
        f"GSTIN: {escape_pdf_text(company_details['gstin'])}",
        style_subtitle,
    ),
]
