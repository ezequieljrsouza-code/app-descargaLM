import streamlit as st
import pandas as pd
import easyocr
import re
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

st.set_page_config(page_title="Monitoramento LH - Painel", layout="wide")

st.title("📦 Monitoramento LH")

DEFAULT_STATUS_OPTIONS = [
    "Não Chegou",
    "Aguardando Doca",
    "Descarga iniciada",
    "Concluída",
    "Descarga finalizada",
]

# =========================
# OCR
# =========================
@st.cache_resource
def load_ocr():
    return easyocr.Reader(['pt'])

reader = load_ocr()

def extract_data_from_image(image):
    result = reader.readtext(np.array(image), detail=0)
    text = " ".join(result)

    placa = re.findall(r'[A-Z]{3}[0-9][A-Z0-9][0-9]{2}', text)
    horarios = re.findall(r'\d{2}:\d{2}:\d{2}', text)
    pacotes = re.findall(r'\b\d{1,4}\b', text)

    data = []

    for i, p in enumerate(placa):
        data.append({
            "PLACA": p,
            "YMS IN": horarios[i*2] if len(horarios) > i*2 else "",
            "YMS OUT": horarios[i*2+1] if len(horarios) > i*2+1 else "",
            "PACOTES": pacotes[i] if i < len(pacotes) else "",
            "DOCA": "",
            "STATUS": "Aguardando Doca"
        })

    return pd.DataFrame(data)

# =========================
# GERAR IMAGEM FINAL
# =========================
def generate_panel_image(df):

    width = 1200
    row_height = 60
    header_height = 80
    height = header_height + (len(df) * row_height) + 40

    img = Image.new("RGB", (width, height), "#111111")
    draw = ImageDraw.Draw(img)

    try:
        font_title = ImageFont.truetype("arial.ttf", 40)
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        font_title = ImageFont.load_default()
        font = ImageFont.load_default()

    # Título
    draw.text((width//2, 20), "MONITORAMENTO LH",
              fill="white", font=font_title, anchor="mm")

    headers = ["PLACA", "YMS IN", "YMS OUT", "PACOTES", "DOCA", "STATUS"]
    col_positions = [50, 220, 380, 560, 700, 850]

    y = header_height
    for i, h in enumerate(headers):
        draw.text((col_positions[i], y), h, fill="#00FFAA", font=font)

    y += 50

    for _, row in df.iterrows():
        values = [
            row["PLACA"],
            row["YMS IN"],
            row["YMS OUT"],
            str(row["PACOTES"]),
            row["DOCA"],
            row["STATUS"]
        ]

        for i, value in enumerate(values):
            draw.text((col_positions[i], y), value, fill="white", font=font)

        y += row_height

    return img

# =========================
# Upload
# =========================
uploaded = st.file_uploader("📸 Envie a imagem", type=["png", "jpg", "jpeg"])

if not uploaded:
    st.stop()

image = Image.open(uploaded)
st.image(image, caption="Imagem enviada", use_container_width=True)

if "data" not in st.session_state:
    with st.spinner("Lendo imagem..."):
        st.session_state.data = extract_data_from_image(image)

if st.session_state.data.empty:
    st.warning("Nenhuma placa encontrada.")
    st.stop()

st.success(f"Placas encontradas: {len(st.session_state.data)}")

# =========================
# Tabela Editável
# =========================
edited = st.data_editor(
    st.session_state.data,
    use_container_width=True,
    hide_index=True,
    column_config={
        "DOCA": st.column_config.TextColumn("DOCA"),
        "STATUS": st.column_config.SelectboxColumn(
            "STATUS",
            options=DEFAULT_STATUS_OPTIONS
        )
    }
)

st.session_state.data = edited

# =========================
# Gerar Imagem Final
# =========================
if st.button("🖼️ Gerar Painel Final"):
    final_image = generate_panel_image(edited)

    buffer = BytesIO()
    final_image.save(buffer, format="PNG")
    buffer.seek(0)

    st.image(final_image, caption="Painel Final", use_container_width=True)

    st.download_button(
        "📋 Baixar Imagem",
        data=buffer,
        file_name="monitoramento_lh.png",
        mime="image/png"
    )
