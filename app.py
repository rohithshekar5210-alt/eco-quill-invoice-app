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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable, Image
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

st.set_page_config(page_title="Custom Invoice Generator", page_icon="🧾", layout="wide")

BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
INVOICE_DIR = BASE_DIR / "invoices"

# Repair old zero-byte placeholder files that should be folders.
for folder in (ASSETS_DIR, INVOICE_DIR):
    if folder.exists() and not folder.is_dir():
        folder.unlink()
    folder.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = BASE_DIR / "business_settings.json"
LOGO_PATH = ASSETS_DIR / "business_logo.png"
SIGNATURE_PATH = ASSETS_DIR / "digital_signature.png"
HISTORY_FILE = INVOICE_DIR / "invoice_history.csv"

COLOR_PRIMARY_DARK = "#0B3D2E"
COLOR_PRIMARY = "#145A32"
COLOR_ACCENT_GOLD = "#B8860B"
COLOR_ACCENT_GOLD_LIGHT = "#F4E9D0"
COLOR_TEXT = "#1C2833"
COLOR_MUTED = "#5D6D64"
COLOR_BORDER = "#D8E0D8"
COLOR_ROW_TINT = "#F5F9F5"

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
        "Dear {customer_name},\n\nPlease find attached your invoice from {company_name}.\n\n"
        "Invoice No: {invoice_no}\nInvoice Date: {invoice_date}\nGrand Total: {grand_total}\n\n"
        "Thank you for choosing {company_name}.\n\nRegards,\n{company_name}"
    ),
    "whatsapp_message_template": (
        "Hello {customer_name},\n\nYour invoice from {company_name} is ready.\n"
        "Invoice No: {invoice_no}\nGrand Total: {grand_total}\n\n"
        "Please check your email for the PDF invoice.\n\nThank you,\n{company_name}"
    ),
}


def load_settings():
    result = DEFAULT_SETTINGS.copy()
    if SETTINGS_FILE.exists() and SETTINGS_FILE.is_file():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as file:
                saved = json.load(file)
            if isinstance(saved, dict):
                result.update(saved)
        except Exception:
            pass
    return result


def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)


def save_uploaded_image(uploaded_file, destination):
    if uploaded_file is not None:
        destination.write_bytes(uploaded_file.getbuffer())


settings = load_settings()


def register_invoice_fonts():
    regular_fonts = [
        ASSETS_DIR / "segoeui.ttf",
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    bold_fonts = [
        ASSETS_DIR / "segoeuib.ttf",
        Path("C:/Windows/Fonts/segoeuib.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    regular = next((p for p in regular_fonts if p.exists() and p.is_file()), None)
    bold = next((p for p in bold_fonts if p.exists() and p.is_file()), None)
    if regular and bold:
        pdfmetrics.registerFont(TTFont("InvoiceRegular", str(regular)))
        pdfmetrics.registerFont(TTFont("InvoiceBold", str(bold)))
        return "InvoiceRegular", "InvoiceBold"
    return "Helvetica", "Helvetica-Bold"


FONT_REGULAR, FONT_BOLD = register_invoice_fonts()


def clean_phone_number(phone):
    return re.sub(r"\D", "", phone or "")


def format_inr(amount):
    try:
        return f"₹ {float(amount):,.2f}"
    except Exception:
        return f"₹ {amount}"


def amount_to_words(amount):
    try:
        return f"{num2words(int(round(amount)), lang='en_IN').title()} Rupees Only"
    except Exception:
        return "Amount In Words Not Available"


def safe_filename(text):
    return re.sub(r"[^A-Za-z0-9_-]", "_", str(text))[:80]


def escape_pdf_text(value):
    return str(value or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_template(template, **values):
    try:
        return template.format(**values)
    except Exception:
        return template


def save_invoice_history(row):
    fields = [
        "created_on", "invoice_no", "invoice_date", "customer_name", "customer_phone",
        "customer_email", "taxable_value", "gst_amount", "packing_charges", "grand_total", "pdf_file"
    ]
    exists = HISTORY_FILE.exists()
    with open(HISTORY_FILE, "a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def generate_invoice_pdf(company, customer, invoice, products, totals, bank, terms):
    pdf_name = (
        f"{safe_filename(company['name'])}_Invoice_"
        f"{safe_filename(invoice['invoice_no'])}_{safe_filename(customer['name'])}.pdf"
    )
    pdf_path = INVOICE_DIR / pdf_name
    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4, rightMargin=14 * mm, leftMargin=14 * mm,
        topMargin=12 * mm, bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "CompanyTitle", parent=styles["Title"], fontName=FONT_BOLD,
        fontSize=25, leading=29, textColor=colors.HexColor(COLOR_PRIMARY_DARK),
        alignment=TA_LEFT, spaceAfter=0,
    )
    subtitle = ParagraphStyle(
        "Subtitle", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=9, leading=12, textColor=colors.HexColor(COLOR_MUTED), alignment=TA_LEFT,
    )
    heading = ParagraphStyle(
        "Heading", parent=styles["Heading2"], fontName=FONT_BOLD,
        fontSize=10, textColor=colors.HexColor(COLOR_PRIMARY_DARK), spaceAfter=6,
    )
    normal = ParagraphStyle(
        "NormalInvoice", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=9, leading=12, textColor=colors.HexColor(COLOR_TEXT),
    )
    small = ParagraphStyle(
        "SmallInvoice", parent=styles["Normal"], fontName=FONT_REGULAR,
        fontSize=8, leading=10, textColor=colors.HexColor(COLOR_MUTED),
    )
    right = ParagraphStyle("Right", parent=normal, alignment=TA_RIGHT)
    cell = ParagraphStyle("Cell", parent=normal, fontSize=8, leading=11)
    cell_right = ParagraphStyle("CellRight", parent=cell, alignment=TA_RIGHT)
    cell_center = ParagraphStyle("CellCenter", parent=cell, alignment=TA_CENTER)

    story = []
    company_block = [
        Paragraph(escape_pdf_text(company["name"]), title),
        Spacer(1, 5),
        Paragraph(escape_pdf_text(company["tagline"]), subtitle),
        Paragraph(escape_pdf_text(company["address"]), subtitle),
        Paragraph(
            f"Phone: {escape_pdf_text(company['phone'])} | Email: {escape_pdf_text(company['email'])}",
            subtitle,
        ),
        Paragraph(f"GSTIN: {escape_pdf_text(company['gstin'])}", subtitle),
    ]

    if LOGO_PATH.exists() and LOGO_PATH.is_file():
        try:
            logo = Image(str(LOGO_PATH), width=24 * mm, height=15.2 * mm)
            header = Table([[logo, company_block]], colWidths=[26 * mm, 154 * mm])
            header.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(header)
        except Exception:
            story.extend(company_block)
    else:
        story.extend(company_block)

    story += [
        Spacer(1, 8),
        HRFlowable(width="100%", thickness=1.4, color=colors.HexColor(COLOR_ACCENT_GOLD)),
        Spacer(1, 8),
    ]

    invoice_title_style = ParagraphStyle(
        "InvoiceTitle", parent=normal, fontName=FONT_BOLD,
        fontSize=14, textColor=colors.white, alignment=TA_CENTER,
    )
    invoice_title = Table(
        [[Paragraph(f"<b>{escape_pdf_text(invoice['invoice_title'])}</b>", invoice_title_style)]],
        colWidths=[180 * mm],
    )
    invoice_title.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(COLOR_PRIMARY_DARK)),
        ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor(COLOR_ACCENT_GOLD)),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    story += [invoice_title, Spacer(1, 10)]

    billed = [
        Paragraph("Billed To", heading),
        Paragraph(f"<b>Name:</b> {escape_pdf_text(customer['name'])}", normal),
        Paragraph(f"<b>Address:</b> {escape_pdf_text(customer['address'])}", normal),
        Paragraph(f"<b>Phone:</b> {escape_pdf_text(customer['phone'])}", normal),
        Paragraph(f"<b>WhatsApp:</b> {escape_pdf_text(customer['whatsapp'])}", normal),
        Paragraph(f"<b>Email:</b> {escape_pdf_text(customer['email'] or 'Not provided')}", normal),
        Paragraph(f"<b>Customer GSTIN:</b> {escape_pdf_text(customer['gstin'] or 'Not provided')}", normal),
    ]
    invoice_info = [
        Paragraph("Invoice Details", heading),
        Paragraph(f"<b>Invoice No:</b> {escape_pdf_text(invoice['invoice_no'])}", normal),
        Paragraph(f"<b>Invoice Date:</b> {escape_pdf_text(invoice['invoice_date'])}", normal),
        Paragraph(f"<b>Place of Supply:</b> {escape_pdf_text(invoice['place_of_supply'])}", normal),
        Paragraph(f"<b>Payment Status:</b> {escape_pdf_text(invoice['payment_status'])}", normal),
    ]
    info = Table([[billed, invoice_info]], colWidths=[90 * mm, 90 * mm])
    info.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor(COLOR_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FCF9")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [info, Spacer(1, 12)]

    product_data = [["Sr.", "Description of Goods", "HSN/SAC", "Qty", "Rate", "GST %", "Amount"]]
    for index, row in enumerate(products, 1):
        product_data.append([
            Paragraph(str(index), cell_center),
            Paragraph(escape_pdf_text(row["product_name"]), cell),
            Paragraph(escape_pdf_text(row["hsn"]), cell_center),
            Paragraph(f"{row['quantity']:,.2f}", cell_center),
            Paragraph(format_inr(row["rate"]), cell_right),
            Paragraph(f"{row['gst_percent']:,.2f}%", cell_center),
            Paragraph(format_inr(row["line_amount"]), cell_right),
        ])
    product_table = Table(
        product_data,
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
    story += [product_table, Spacer(1, 12)]

    words = Table([
        [Paragraph("<b>Bill Amount In Words:</b>", normal),
         Paragraph(escape_pdf_text(amount_to_words(totals["grand_total"])), normal)]
    ], colWidths=[45 * mm, 135 * mm])
    words.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDFEFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [words, Spacer(1, 8)]

    total_rows = [
        [Paragraph("Taxable Value", normal), Paragraph(format_inr(totals["taxable_value"]), cell_right)],
        [Paragraph("Packing / Delivery Charges", normal), Paragraph(format_inr(totals["packing_charges"]), cell_right)],
        [Paragraph("GST Amount", normal), Paragraph(format_inr(totals["gst_amount"]), cell_right)],
        [Paragraph("<b>Grand Total</b>", normal), Paragraph(f"<b>{format_inr(totals['grand_total'])}</b>", cell_right)],
    ]
    total_table = Table(total_rows, colWidths=[125 * mm, 55 * mm])
    total_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor(COLOR_ACCENT_GOLD_LIGHT)),
        ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor(COLOR_ACCENT_GOLD)),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story += [total_table, Spacer(1, 12)]

    bank_text = (
        f"<b>Bank Details</b><br/>Bank Name: {escape_pdf_text(bank['bank_name'])}<br/>"
        f"Account Name: {escape_pdf_text(bank['account_name'])}<br/>"
        f"Account No: {escape_pdf_text(bank['account_no'])}<br/>"
        f"IFSC Code: {escape_pdf_text(bank['ifsc'])}<br/>UPI ID: {escape_pdf_text(bank['upi'])}"
    )
    terms_text = "<b>Terms &amp; Conditions</b><br/>" + "<br/>".join(
        f"{i}. {escape_pdf_text(term)}" for i, term in enumerate(terms, 1)
    )
    bottom = Table(
        [[Paragraph(bank_text, small), Paragraph(terms_text, small)]],
        colWidths=[90 * mm, 90 * mm],
    )
    bottom.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor(COLOR_BORDER)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFC")),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story += [bottom, Spacer(1, 14)]

    signature = []
    if SIGNATURE_PATH.exists() and SIGNATURE_PATH.is_file():
        try:
            signature.append(Image(str(SIGNATURE_PATH), width=32 * mm, height=16 * mm))
        except Exception:
            pass
    signature.append(Paragraph(
        f"<b>For {escape_pdf_text(company['name'])}</b><br/>Authorised Signatory", right
    ))
    signature_table = Table([["", signature]], colWidths=[90 * mm, 90 * mm])
    signature_table.setStyle(TableStyle([
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
    ]))
    story.append(signature_table)
    doc.build(story)
    return pdf_path


def send_invoice_email(sender_email, sender_password, recipients, subject, body, attachment_path):
    recipients = [x.strip() for x in recipients if x and x.strip()]
    if not sender_email or not sender_password:
        return False, "Email sender ID or app password is missing."
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
    number = clean_phone_number(customer_whatsapp)
    if not number:
        return ""
    if len(number) == 10:
        number = "91" + number
    return f"https://wa.me/{number}?text={urllib.parse.quote(message)}"


st.markdown(f"""
<style>
.main {{ background-color: #F7FAF7; }}
.block-container {{ padding-top: 1.5rem; padding-bottom: 2rem; }}
.hero-card {{ padding: 26px 28px; border-radius: 18px; background: linear-gradient(135deg, {COLOR_PRIMARY_DARK} 0%, {COLOR_PRIMARY} 55%, #1E7A4A 100%); color: white; box-shadow: 0 8px 24px rgba(11,61,46,.22); margin-bottom: 20px; border-bottom: 3px solid {COLOR_ACCENT_GOLD}; }}
.hero-title {{ font-size: 34px; font-weight: 800; margin-bottom: 4px; letter-spacing: .3px; }}
.hero-subtitle {{ font-size: 15px; opacity: .95; }}
.section-card {{ padding: 20px; border-radius: 16px; background: white; border: 1px solid #E5E8E8; border-top: 3px solid {COLOR_ACCENT_GOLD}; box-shadow: 0 4px 16px rgba(0,0,0,.04); margin-bottom: 16px; }}
.success-box {{ padding: 14px; border-radius: 12px; background: {COLOR_ACCENT_GOLD_LIGHT}; border-left: 5px solid {COLOR_ACCENT_GOLD}; color: {COLOR_PRIMARY_DARK}; font-weight: 600; }}
div.stButton > button:first-child {{ background: {COLOR_PRIMARY_DARK}; color: white; border-radius: 10px; border: 1px solid {COLOR_ACCENT_GOLD}; padding: .6rem 1rem; font-weight: 700; }}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("Template Settings")
    st.caption("Edit once and click Save. The details remain saved for future invoices.")
    with st.expander("Business Details", expanded=True):
        company_name_setting = st.text_input("Business Name", settings["company_name"])
        company_tagline_setting = st.text_input("Tagline", settings["company_tagline"])
        company_address_setting = st.text_area("Business Address", settings["company_address"])
        company_phone_setting = st.text_input("Business Phone", settings["company_phone"])
        company_email_setting = st.text_input("Business Email", settings["company_email"])
        company_gstin_setting = st.text_input("GSTIN / Tax Number", settings["company_gstin"])
    with st.expander("Invoice Defaults"):
        invoice_title_setting = st.text_input("Invoice Heading", settings["invoice_title"])
        invoice_prefix_setting = st.text_input("Invoice Number Prefix", settings["invoice_prefix"])
        supply_setting = st.text_input("Default Place of Supply", settings["default_place_of_supply"])
    with st.expander("Bank Details"):
        bank_name_setting = st.text_input("Bank Name", settings["bank_name"])
        account_name_setting = st.text_input("Account Name", settings["account_name"])
        account_no_setting = st.text_input("Account Number", settings["account_no"])
        ifsc_setting = st.text_input("IFSC Code", settings["ifsc_code"])
        upi_setting = st.text_input("UPI ID", settings["upi_id"])
    with st.expander("Terms and Conditions"):
        terms_setting = st.text_area("Enter one term per line", settings["terms_conditions"], height=180)
    with st.expander("Logo and Signature"):
        uploaded_logo = st.file_uploader("Upload Business Logo", type=["png", "jpg", "jpeg"])
        if LOGO_PATH.exists() and LOGO_PATH.is_file():
            st.image(str(LOGO_PATH), caption="Current logo", width=140)
        uploaded_signature = st.file_uploader("Upload Signature Image", type=["png", "jpg", "jpeg"])
        if SIGNATURE_PATH.exists() and SIGNATURE_PATH.is_file():
            st.image(str(SIGNATURE_PATH), caption="Current signature", width=140)
    with st.expander("Email and WhatsApp Templates"):
        email_subject_setting = st.text_input("Email Subject", settings["email_subject_template"])
        email_message_setting = st.text_area("Email Message", settings["email_message_template"], height=240)
        whatsapp_setting = st.text_area("WhatsApp Message", settings["whatsapp_message_template"], height=220)
    if st.button("Save Template Settings", use_container_width=True):
        updated = {
            "company_name": company_name_setting,
            "company_tagline": company_tagline_setting,
            "company_address": company_address_setting,
            "company_phone": company_phone_setting,
            "company_email": company_email_setting,
            "company_gstin": company_gstin_setting,
            "invoice_title": invoice_title_setting,
            "invoice_prefix": invoice_prefix_setting,
            "default_place_of_supply": supply_setting,
            "bank_name": bank_name_setting,
            "account_name": account_name_setting,
            "account_no": account_no_setting,
            "ifsc_code": ifsc_setting,
            "upi_id": upi_setting,
            "terms_conditions": terms_setting,
            "email_subject_template": email_subject_setting,
            "email_message_template": email_message_setting,
            "whatsapp_message_template": whatsapp_setting,
        }
        save_settings(updated)
        save_uploaded_image(uploaded_logo, LOGO_PATH)
        save_uploaded_image(uploaded_signature, SIGNATURE_PATH)
        st.success("Template settings saved permanently.")
        st.rerun()
    st.divider()
    st.subheader("Email Setup")
    sender_email = os.getenv("INVOICE_EMAIL_ID", os.getenv("ECOQUILL_EMAIL_ID", settings["company_email"]))
    sender_password = os.getenv("INVOICE_EMAIL_APP_PASSWORD", os.getenv("ECOQUILL_EMAIL_APP_PASSWORD", ""))
    st.success("Email app password found.") if sender_password else st.warning("Email password not found. PDF and WhatsApp will still work.")

st.markdown(f"""
<div class="hero-card"><div class="hero-title">{escape_pdf_text(settings['company_name'])} Invoice Generator</div>
<div class="hero-subtitle">Create professional GST-style PDF invoices using your saved business template.</div></div>
""", unsafe_allow_html=True)

left_col, right_col = st.columns([1.1, 0.9])
with left_col:
    st.subheader("Customer Details")
    customer_name = st.text_input("Customer Name", placeholder="Enter customer name")
    customer_address = st.text_area("Customer Address", placeholder="Enter customer full address")
    customer_phone = st.text_input("Customer Phone Number", placeholder="Example: 9876543210")
    customer_whatsapp = st.text_input("Customer WhatsApp Number", placeholder="Example: 9876543210")
    customer_email = st.text_input("Customer Email Address Optional", placeholder="customer@example.com")
    customer_gstin = st.text_input("Customer GSTIN Optional", placeholder="Enter GSTIN if available")
with right_col:
    st.subheader("Invoice Details")
    invoice_no = st.text_input("Invoice Number", f"{settings['invoice_prefix']}-{datetime.now().strftime('%Y%m%d-%H%M')}")
    invoice_date = st.date_input("Invoice Date", date.today())
    place_of_supply = st.text_input("Place of Supply", settings["default_place_of_supply"])
    payment_status = st.selectbox("Payment Status", ["Pending", "Paid", "Partially Paid"])
    packing_charges = st.number_input("Packing / Delivery Charges", min_value=0.0, value=0.0, step=10.0)

st.subheader("Product Details")
number_of_items = st.number_input("How many product rows?", 1, 20, 1, 1)
product_rows = []
for i in range(int(number_of_items)):
    st.markdown(f"#### Product {i + 1}")
    c1, c2, c3, c4, c5 = st.columns([2.2, 1, 1, 1, 1])
    with c1:
        product_name = st.text_input(f"Product Name {i + 1}", "BIO CARRY BAG", key=f"product_name_{i}")
    with c2:
        hsn = st.text_input(f"HSN/SAC {i + 1}", "39232990", key=f"hsn_{i}")
    with c3:
        quantity = st.number_input(f"Qty {i + 1}", 0.0, value=1.0, step=1.0, key=f"quantity_{i}")
    with c4:
        rate = st.number_input(f"Rate {i + 1}", 0.0, value=0.0, step=1.0, key=f"rate_{i}")
    with c5:
        gst_percent = st.number_input(f"GST % {i + 1}", 0.0, 100.0, 5.0, 0.5, key=f"gst_{i}")
    line_amount = quantity * rate
    product_rows.append({
        "product_name": product_name, "hsn": hsn, "quantity": quantity,
        "rate": rate, "gst_percent": gst_percent, "line_amount": line_amount,
        "gst_amount": line_amount * gst_percent / 100,
    })

taxable_value = sum(row["line_amount"] for row in product_rows)
gst_amount = sum(row["gst_amount"] for row in product_rows)
grand_total = taxable_value + gst_amount + packing_charges
m1, m2, m3, m4 = st.columns(4)
m1.metric("Taxable Value", format_inr(taxable_value))
m2.metric("GST Amount", format_inr(gst_amount))
m3.metric("Packing / Delivery", format_inr(packing_charges))
m4.metric("Grand Total", format_inr(grand_total))

company_details = {
    "name": settings["company_name"], "tagline": settings["company_tagline"],
    "address": settings["company_address"], "phone": settings["company_phone"],
    "email": settings["company_email"], "gstin": settings["company_gstin"],
}
bank_details = {
    "bank_name": settings["bank_name"], "account_name": settings["account_name"],
    "account_no": settings["account_no"], "ifsc": settings["ifsc_code"], "upi": settings["upi_id"],
}
terms = [x.strip() for x in settings["terms_conditions"].splitlines() if x.strip()]

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
    customer = {
        "name": customer_name, "address": customer_address, "phone": customer_phone,
        "whatsapp": customer_whatsapp, "email": customer_email, "gstin": customer_gstin,
    }
    invoice = {
        "invoice_title": settings["invoice_title"], "invoice_no": invoice_no,
        "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "place_of_supply": place_of_supply, "payment_status": payment_status,
    }
    totals = {
        "taxable_value": taxable_value, "gst_amount": gst_amount,
        "packing_charges": packing_charges, "grand_total": grand_total,
    }
    pdf_path = generate_invoice_pdf(company_details, customer, invoice, product_rows, totals, bank_details, terms)
    save_invoice_history({
        "created_on": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "invoice_no": invoice_no, "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "customer_name": customer_name, "customer_phone": customer_phone,
        "customer_email": customer_email, "taxable_value": taxable_value,
        "gst_amount": gst_amount, "packing_charges": packing_charges,
        "grand_total": grand_total, "pdf_file": str(pdf_path),
    })
    st.markdown(f'<div class="success-box">Invoice PDF generated successfully: {pdf_path.name}</div>', unsafe_allow_html=True)
    st.download_button("Download Invoice PDF", pdf_path.read_bytes(), pdf_path.name, "application/pdf")
    values = {
        "company_name": settings["company_name"], "customer_name": customer_name,
        "invoice_no": invoice_no, "invoice_date": invoice_date.strftime("%d-%m-%Y"),
        "grand_total": format_inr(grand_total),
    }
    recipients = [settings["company_email"]] + ([customer_email.strip()] if customer_email.strip() else [])
    if sender_password:
        success, message = send_invoice_email(
            sender_email, sender_password, recipients,
            render_template(settings["email_subject_template"], **values),
            render_template(settings["email_message_template"], **values), pdf_path,
        )
        st.success(message) if success else st.warning(f"Invoice created, but email failed: {message}")
    else:
        st.warning("Invoice created. Email was not sent because the email app password is not set.")
    whatsapp_link = generate_whatsapp_link(
        customer_whatsapp, render_template(settings["whatsapp_message_template"], **values)
    )
    if whatsapp_link:
        st.link_button("Share Invoice Details on WhatsApp", whatsapp_link)

st.subheader("Invoice History")
if HISTORY_FILE.exists() and HISTORY_FILE.is_file():
    st.download_button("Download Invoice History CSV", HISTORY_FILE.read_text(encoding="utf-8"), "invoice_history.csv", "text/csv")
    st.caption("Invoice history is saved inside the invoices folder.")
else:
    st.caption("No invoice history found yet.")
