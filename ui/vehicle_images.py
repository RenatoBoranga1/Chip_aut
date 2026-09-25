"""Portuguese visual presentation, without business writes."""

import base64
from functools import lru_cache
from io import BytesIO

import streamlit as st
from PIL import Image, ImageDraw

from services.vehicle_image_config import load_image_config, should_show_vehicle_image
from services.vehicle_image_metrics import metrics
from services.vehicle_images import filter_photos, photo_summary, resolve_photo, thumbnail, visible_photos


@lru_cache(maxsize=1)
def placeholder():
    image = Image.new("RGB", (140, 88), "#eef1f4")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((47, 25, 93, 62), radius=4, outline="#8b97a3", width=2)
    draw.ellipse((57, 32, 63, 38), fill="#8b97a3")
    draw.line([(51, 57), (65, 44), (73, 51), (81, 42), (90, 55)], fill="#8b97a3", width=2)
    output = BytesIO()
    image.save(output, "JPEG", quality=85)
    return output.getvalue()


def photo_message(photo):
    return "Não foi possível carregar a foto" if photo.status == "failed" else "Foto não disponível"


def photo_cells(rows, config):
    photos = visible_photos(rows, config)
    cells = []
    for row, photo in zip(rows, photos):
        if not should_show_vehicle_image(row, config):
            cells.append("")
            continue
        content = photo.content or placeholder()
        message = "Foto do anúncio" if photo.content else photo_message(photo)
        cells.append(
            "!["
            + message
            + "](data:image/jpeg;base64,"
            + base64.b64encode(content).decode()
            + ")"
            + ("\n\n" + message if not photo.content else "")
        )
    eligible = sum(p.status != "disabled" for p in photos)
    available = sum(bool(p.content) for p in photos)
    if eligible:
        st.caption(
            f"Miniaturas disponíveis neste bloco: {available}/{eligible} ({available / eligible:.0%}). Imagens são apenas apoio visual."
        )
    return cells


def photo_filter(rows, key):
    choice = st.selectbox("Fotos", ["Todas", "Com foto", "Sem foto"], key="photos_" + key)
    st.caption(
        "O filtro considera fotos informadas pelo anúncio; a disponibilidade é confirmada somente no bloco exibido."
    )
    return filter_photos(rows, choice)


def photo_metrics(rows):
    config = load_image_config()
    if not config.enabled:
        return
    summary = photo_summary(rows, config)
    with st.expander("Disponibilidade de fotos"):
        cols = st.columns(3)
        cols[0].metric("Casos relevantes com foto informada", summary["with_photo"])
        cols[1].metric("Casos relevantes sem foto informada", summary["without_photo"])
        cols[2].metric("Falhas de carregamento nos últimos 15 minutos", metrics()["recent_failures"])
        st.caption("Indicadores de imagem deste processo local. Não representam identidade, suporte ou prioridade.")


def vehicle_photo(ad, context, *, detail=False, alert_type=None, force=False):
    config = load_image_config()
    if not config.enabled or (not force and not should_show_vehicle_image(context, config, alert_type=alert_type)):
        return
    expanded = detail and st.checkbox(
        "Ampliar foto", key=f"enlarge_photo_{ad.get('partner')}_{ad.get('external_id')}_{alert_type}"
    )
    photo = resolve_photo(ad, config, detail=expanded, loader=thumbnail)
    if photo.content:
        st.image(
            photo.content, width=420 if expanded else config.thumbnail_width, caption="Foto do anúncio · apoio visual"
        )
        if photo.source == "saved":
            st.caption("Foto salva de uma observação anterior deste anúncio.")
    else:
        st.image(placeholder(), width=config.thumbnail_width, caption=photo_message(photo))
