"""Portuguese visual presentation, without business writes."""

import base64

import streamlit as st

from services.vehicle_image_config import load_image_config, should_show_vehicle_image
from services.vehicle_images import thumbnail, visible_thumbnails


def photo_cells(rows, config):
    photos = visible_thumbnails(rows, config)
    cells = []
    for row in rows:
        if not should_show_vehicle_image(row, config):
            cells.append("")
            continue
        content = photos.get(row.get("primary_image_url"))
        cells.append(
            "![Foto do anúncio](data:image/jpeg;base64," + base64.b64encode(content).decode() + ")"
            if content
            else "Foto não disponível"
        )
    return cells


def vehicle_photo(ad, context, *, detail=False, alert_type=None):
    config = load_image_config()
    if not should_show_vehicle_image(context, config, alert_type=alert_type):
        return
    content = thumbnail(ad.get("primary_image_url"), config, detail=detail)
    if content:
        st.image(content, width=420 if detail else config.thumbnail_width, caption="Foto do anúncio · apoio visual")
    else:
        st.caption("Foto não disponível")
