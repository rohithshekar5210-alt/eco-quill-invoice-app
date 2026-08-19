import os
import re
import csv
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
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    HRFlowable,
)


# =========================================================
# APP CONFIG
# =========================================================

st.set_page_config(
    page_title="Eco Quill Invoice Generator", page_icon="🧾", layout="wide"
)

INVOICE_DIR = Path("invoices")

if not INVOICE_DIR.exists():
    INVOICE_DIR.mkdir(parents=True)

HISTORY_FILE = INVOICE_DIR / "invoice_history.csv"


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
    text = re.sub(r"[^A-Za-z0-9_-]", "_", text)
    return text[:80]


def save_invoice_history(invoice_data):
    file_exists = HISTORY_FILE.exists()

    fieldnames = [
        "created_on",
        "invoice_no",
        "invoice_date",
        "customer_name",
        "customer_phone",
        "customer_email",
        "taxable_value",
        "gst_amount",
        "packing_charges",
        "grand_total",
        "pdf_file",
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
    pdf_filename = f"Eco_Quill_Invoice_{invoice_no_file}_{customer_file}.pdf"
    pdf_path = INVOICE_DIR / pdf_filename

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontName="Helvetica-Bold",
        fontSize=22,
        textColor=colors.HexColor("#145A32"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )

    style_subtitle = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#4D5656"),
        alignment=TA_CENTER,
        leading=12,
    )

    style_heading = ParagraphStyle(
        "HeadingStyle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#145A32"),
        spaceAfter=6,
    )

    style_normal = ParagraphStyle(
        "NormalStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1C2833"),
    )

    style_small = ParagraphStyle(
        "SmallStyle",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#566573"),
    )

    style_right = ParagraphStyle(
        "RightStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        alignment=TA_RIGHT,
    )

    story = []

    # Header
    story.append(Paragraph(company_details["name"], style_title))
    story.append(Paragraph(company_details["tagline"], style_subtitle))
    story.append(Paragraph(company_details["address"], style_subtitle))
    story.append(
        Paragraph(
            f"Phone: {company_details['phone']} | Email: {company_details['email']} | GSTIN: {company_details['gstin']}",
            style_subtitle,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#145A32"))
    )
    story.append(Spacer(1, 8))

    # Invoice title row
    title_table = Table(
        [
            [
                Paragraph(
                    "<b>TAX INVOICE</b>",
                    ParagraphStyle(
                        "InvoiceTitle",
                        parent=styles["Normal"],
                        fontName="Helvetica-Bold",
                        fontSize=15,
                        textColor=colors.white,
                        alignment=TA_CENTER,
                    ),
                )
            ]
        ],
        colWidths=[180 * mm],
    )

    title_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#145A32")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#145A32")),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    story.append(title_table)
    story.append(Spacer(1, 10))

    # Customer and invoice information
    billed_to = [
        Paragraph("<b>Billed To</b>", style_heading),
        Paragraph(f"<b>Name:</b> {customer_details['name']}", style_normal),
        Paragraph(f"<b>Address:</b> {customer_details['address']}", style_normal),
        Paragraph(f"<b>Phone:</b> {customer_details['phone']}", style_normal),
        Paragraph(f"<b>WhatsApp:</b> {customer_details['whatsapp']}", style_normal),
        Paragraph(
            f"<b>Email:</b> {customer_details['email'] or 'Not provided'}", style_normal
        ),
        Paragraph(
            f"<b>Customer GSTIN:</b> {customer_details['gstin'] or 'Not provided'}",
            style_normal,
        ),
    ]

    invoice_info = [
        Paragraph("<b>Invoice Details</b>", style_heading),
        Paragraph(f"<b>Invoice No:</b> {invoice_details['invoice_no']}", style_normal),
        Paragraph(
            f"<b>Invoice Date:</b> {invoice_details['invoice_date']}", style_normal
        ),
        Paragraph(
            f"<b>Place of Supply:</b> {invoice_details['place_of_supply']}",
            style_normal,
        ),
        Paragraph(
            f"<b>Payment Status:</b> {invoice_details['payment_status']}", style_normal
        ),
    ]

    info_table = Table([[billed_to, invoice_info]], colWidths=[90 * mm, 90 * mm])

    info_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#D5DBDB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FCF9")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    story.append(info_table)
    story.append(Spacer(1, 12))

    # Product table
    data = [
        ["Sr.", "Description of Goods", "HSN/SAC", "Qty", "Rate", "GST %", "Amount"]
    ]

    for index, row in enumerate(product_rows, start=1):
        data.append(
            [
                index,
                Paragraph(row["product_name"], style_normal),
                row["hsn"],
                f"{row['quantity']:,.2f}",
                format_inr(row["rate"]),
                f"{row['gst_percent']:,.2f}%",
                format_inr(row["line_amount"]),
            ]
        )

    product_table = Table(
        data,
        colWidths=[12 * mm, 61 * mm, 22 * mm, 18 * mm, 24 * mm, 18 * mm, 25 * mm],
        repeatRows=1,
    )

    product_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#145A32")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (0, 1), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                ("ALIGN", (6, 1), (6, -1), "RIGHT"),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F8F9F9")],
                ),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story.append(product_table)
    story.append(Spacer(1, 12))

    # Amount in words and totals
    amount_words = amount_to_words(totals["grand_total"])

    amount_words_table = Table(
        [
            [
                Paragraph("<b>Bill Amount In Words:</b>", style_normal),
                Paragraph(amount_words, style_normal),
            ]
        ],
        colWidths=[45 * mm, 135 * mm],
    )

    amount_words_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FDFEFE")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story.append(amount_words_table)
    story.append(Spacer(1, 8))

    totals_data = [
        ["Taxable Value", format_inr(totals["taxable_value"])],
        ["Packing / Delivery Charges", format_inr(totals["packing_charges"])],
        ["GST Amount", format_inr(totals["gst_amount"])],
        ["Grand Total", format_inr(totals["grand_total"])],
    ]

    totals_table = Table(totals_data, colWidths=[125 * mm, 55 * mm])

    totals_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E8F6EF")),
                ("TEXTCOLOR", (0, -1), (-1, -1), colors.HexColor("#145A32")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )

    story.append(totals_table)
    story.append(Spacer(1, 12))

    # Bank details and terms
    bank_text = f"""
    <b>Bank Details</b><br/>
    Bank Name: {bank_details["bank_name"]}<br/>
    Account Name: {bank_details["account_name"]}<br/>
    Account No: {bank_details["account_no"]}<br/>
    IFSC Code: {bank_details["ifsc"]}<br/>
    UPI ID: {bank_details["upi"]}
    """

    terms_text = "<b>Terms & Conditions</b><br/>" + "<br/>".join(
        [f"{i + 1}. {term}" for i, term in enumerate(terms_conditions)]
    )

    bottom_table = Table(
        [[Paragraph(bank_text, style_small), Paragraph(terms_text, style_small)]],
        colWidths=[90 * mm, 90 * mm],
    )

    bottom_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DBDB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FBFCFC")),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    story.append(bottom_table)
    story.append(Spacer(1, 20))

    # Signature
    signature_table = Table(
        [
            [
                "",
                Paragraph(
                    f"<b>For {company_details['name']}</b><br/><br/><br/>Authorised Signatory",
                    style_right,
                ),
            ]
        ],
        colWidths=[90 * mm, 90 * mm],
    )

    signature_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
            ]
        )
    )

    story.append(signature_table)

    doc.build(story)

    return pdf_path


# =========================================================
# EMAIL FUNCTION
# =========================================================


def send_invoice_email(
    sender_email, sender_password, recipients, subject, body, attachment_path
):
    if not sender_email or not sender_password:
        return (
            False,
            "Email sender ID or app password is missing in environment variables.",
        )

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
            file_data = file.read()
            file_name = os.path.basename(attachment_path)

        msg.add_attachment(
            file_data, maintype="application", subtype="pdf", filename=file_name
        )

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)

        return True, "Email sent successfully."

    except Exception as error:
        return False, str(error)


# =========================================================
# WHATSAPP LINK FUNCTION
# =========================================================


def generate_whatsapp_link(customer_whatsapp, customer_name, invoice_no, grand_total):
    clean_number = clean_phone_number(customer_whatsapp)

    if not clean_number:
        return ""

    if len(clean_number) == 10:
        clean_number = "91" + clean_number

    message = (
        f"Hello {customer_name},\n\n"
        f"Your Eco Quill invoice is ready.\n"
        f"Invoice No: {invoice_no}\n"
        f"Grand Total: {format_inr(grand_total)}\n\n"
        f"Please check your email for the PDF invoice.\n\n"
        f"Thank you,\n"
        f"Eco Quill"
    )

    encoded_message = urllib.parse.quote(message)
    return f"https://wa.me/{clean_number}?text={encoded_message}"


# =========================================================
# PREMIUM CSS
# =========================================================

st.markdown(
    """
    <style>
    .main {
        background-color: #F7FAF7;
    }

    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    .hero-card {
        padding: 24px;
        border-radius: 18px;
        background: linear-gradient(135deg, #145A32 0%, #1E8449 50%, #52BE80 100%);
        color: white;
        box-shadow: 0 8px 24px rgba(20, 90, 50, 0.18);
        margin-bottom: 20px;
    }

    .hero-title {
        font-size: 34px;
        font-weight: 800;
        margin-bottom: 4px;
    }

    .hero-subtitle {
        font-size: 15px;
        opacity: 0.95;
    }

    .section-card {
        padding: 20px;
        border-radius: 16px;
        background-color: white;
        border: 1px solid #E5E8E8;
        box-shadow: 0 4px 16px rgba(0,0,0,0.04);
        margin-bottom: 16px;
    }

    .success-box {
        padding: 14px;
        border-radius: 12px;
        background-color: #E8F6EF;
        border-left: 5px solid #145A32;
        color: #145A32;
        font-weight: 600;
    }

    .warning-box {
        padding: 14px;
        border-radius: 12px;
        background-color: #FEF5E7;
        border-left: 5px solid #F39C12;
        color: #7E5109;
        font-weight: 600;
    }

    div.stButton > button:first-child {
        background-color: #145A32;
        color: white;
        border-radius: 10px;
        border: none;
        padding: 0.6rem 1rem;
        font-weight: 700;
    }

    div.stButton > button:first-child:hover {
        background-color: #0B3D21;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# UI HEADER
# =========================================================

st.markdown(
    """
    <div class="hero-card">
        <div class="hero-title">Eco Quill Invoice Generator</div>
        <div class="hero-subtitle">Generate professional GST-style PDF invoices, email them automatically, and share invoice details on WhatsApp.</div>
    </div>
    """,
    unsafe_allow_html=True,
)


# =========================================================
# SIDEBAR COMPANY SETTINGS
# =========================================================

with st.sidebar:
    st.header("Eco Quill Settings")

    company_name = st.text_input("Company Name", value="Eco Quill")
    company_tagline = st.text_input("Tagline", value="Eco-Friendly Bio Bags")
    company_address = st.text_area(
        "Company Address",
        value="660, 9th Cross, Weavers Colony, Gottigere Post, Bannerghatta Road, Bangalore - 560083",
    )
    company_phone = st.text_input("Company Phone", value="+91 9535190713")
    company_email = st.text_input("Company Email", value="ecoquill.biobags@gmail.com")
    company_gstin = st.text_input("Company GSTIN", value="GSTIN Placeholder")

    st.divider()

    st.subheader("Bank Details")
    bank_name = st.text_input("Bank Name", value="Bank Name Placeholder")
    account_name = st.text_input("Account Name", value="Eco Quill")
    account_no = st.text_input("Account Number", value="Account Number Placeholder")
    ifsc_code = st.text_input("IFSC Code", value="IFSC Placeholder")
    upi_id = st.text_input("UPI ID", value="UPI Placeholder")

    st.divider()

    st.subheader("Email Setup")
    st.caption("Keep password in environment variable. Do not paste password in code.")
    sender_email = os.getenv("ECOQUILL_EMAIL_ID", company_email)
    sender_password = os.getenv("ECOQUILL_EMAIL_APP_PASSWORD", "")

    if sender_password:
        st.success("Email app password found.")
    else:
        st.warning(
            "Email app password not found. PDF will still generate, but email sending will be skipped."
        )


# =========================================================
# MAIN FORM
# =========================================================

left_col, right_col = st.columns([1.1, 0.9])

with left_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Customer Details")

    customer_name = st.text_input("Customer Name", placeholder="Enter customer name")
    customer_address = st.text_area(
        "Customer Address", placeholder="Enter customer full address"
    )
    customer_phone = st.text_input(
        "Customer Phone Number", placeholder="Example: 9876543210"
    )
    customer_whatsapp = st.text_input(
        "Customer WhatsApp Number", placeholder="Example: 9876543210"
    )
    customer_email = st.text_input(
        "Customer Email Address Optional", placeholder="customer@example.com"
    )
    customer_gstin = st.text_input(
        "Customer GSTIN Optional", placeholder="Enter GSTIN if available"
    )

    st.markdown("</div>", unsafe_allow_html=True)

with right_col:
    st.markdown('<div class="section-card">', unsafe_allow_html=True)
    st.subheader("Invoice Details")

    default_invoice_no = f"EQ-{datetime.now().strftime('%Y%m%d-%H%M')}"
    invoice_no = st.text_input("Invoice Number", value=default_invoice_no)
    invoice_date = st.date_input("Invoice Date", value=date.today())
    place_of_supply = st.text_input("Place of Supply", value="Karnataka")
    payment_status = st.selectbox(
        "Payment Status", ["Pending", "Paid", "Partially Paid"]
    )

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
    "How many product rows?", min_value=1, max_value=10, value=1, step=1
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
            f"GST % {i + 1}",
            min_value=0.0,
            max_value=100.0,
            value=5.0,
            step=0.5,
            key=f"gst_{i}",
        )

    line_amount = quantity * rate
    gst_amount_for_line = line_amount * gst_percent / 100

    product_rows.append(
        {
            "product_name": product_name,
            "hsn": hsn,
            "quantity": quantity,
            "rate": rate,
            "gst_percent": gst_percent,
            "line_amount": line_amount,
            "gst_amount": gst_amount_for_line,
        }
    )

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
    "name": company_name,
    "tagline": company_tagline,
    "address": company_address,
    "phone": company_phone,
    "email": company_email,
    "gstin": company_gstin,
}

bank_details = {
    "bank_name": bank_name,
    "account_name": account_name,
    "account_no": account_no,
    "ifsc": ifsc_code,
    "upi": upi_id,
}

terms_conditions = [
    "Goods once sold will not be taken back.",
    "Payment should be made as per agreed terms.",
    "Any dispute is subject to Bangalore jurisdiction only.",
    "Please verify quantity and product details at the time of delivery.",
    "This is a computer-generated invoice.",
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
        company_details=company_details,
        customer_details=customer_details,
        invoice_details=invoice_details,
        product_rows=product_rows,
        totals=totals,
        bank_details=bank_details,
        terms_conditions=terms_conditions,
    )

    save_invoice_history(
        {
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
        }
    )

    st.markdown(
        f"""
        <div class="success-box">
        Invoice PDF generated successfully: {pdf_path.name}
        </div>
        """,
        unsafe_allow_html=True,
    )

    with open(pdf_path, "rb") as pdf_file:
        st.download_button(
            label="Download Invoice PDF",
            data=pdf_file,
            file_name=pdf_path.name,
            mime="application/pdf",
        )

    recipients = [company_email]

    if customer_email.strip():
        recipients.append(customer_email.strip())

    email_subject = f"Eco Quill Invoice {invoice_no}"
    email_body = f"""
Dear {customer_name},

Please find attached your invoice from Eco Quill.

Invoice No: {invoice_no}
Invoice Date: {invoice_date.strftime("%d-%m-%Y")}
Grand Total: {format_inr(grand_total)}

Thank you for choosing Eco Quill.

Regards,
Eco Quill
"""

    if sender_password:
        email_success, email_message = send_invoice_email(
            sender_email=sender_email,
            sender_password=sender_password,
            recipients=recipients,
            subject=email_subject,
            body=email_body,
            attachment_path=pdf_path,
        )

        if email_success:
            st.success(
                "Invoice email sent successfully to Eco Quill and available customer email."
            )
        else:
            st.warning(f"Invoice created, but email sending failed: {email_message}")
    else:
        st.warning(
            "Invoice created. Email not sent because ECOQUILL_EMAIL_APP_PASSWORD is not set."
        )

    whatsapp_link = generate_whatsapp_link(
        customer_whatsapp=customer_whatsapp,
        customer_name=customer_name,
        invoice_no=invoice_no,
        grand_total=grand_total,
    )
# =========================================================
# HISTORY SECTION
# =========================================================

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.subheader("Invoice History")

if HISTORY_FILE.exists():
    with open(HISTORY_FILE, mode="r", encoding="utf-8") as file:
        history_content = file.read()

    st.download_button(
        label="Download Invoice History CSV",
        data=history_content,
        file_name="invoice_history.csv",
        mime="text/csv",
    )

    st.caption("Invoice history is saved inside the invoices folder.")
else:
    st.caption("No invoice history found yet.")

st.markdown("</div>", unsafe_allow_html=True)
