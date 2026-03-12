import base64
import io
import logging
import uuid

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import re


def _parse_color(color_str: str) -> str:
    """Converteer CSS kleur (hex of rgb()) naar 6-digit hex string zonder #."""
    if not color_str:
        return "000000"
    color_str = color_str.strip()
    # rgb(r, g, b) formaat
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", color_str)
    if m:
        return f"{int(m.group(1)):02x}{int(m.group(2)):02x}{int(m.group(3)):02x}"
    # hex formaat
    h = color_str.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    if len(h) == 6:
        return h
    return "000000"


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory session store — sessies worden verwijderd na opslaan
sessions: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "rb") as f:
        return HTMLResponse(content=f.read())


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Alleen PDF-bestanden zijn toegestaan.")

    try:
        pdf_bytes = await file.read()
        logger.info(f"PDF ontvangen: {file.filename}, {len(pdf_bytes)} bytes")
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Fout bij openen PDF: {e}")
        raise HTTPException(status_code=400, detail=f"Kon PDF niet openen: {str(e)}")

    try:
        pages = []
        logger.info(f"Verwerking: {len(doc)} pagina's")
        for page in doc:
            text_dict = page.get_text("dict")
            width = page.rect.width
            height = page.rect.height

            blocks = []
            for block in text_dict["blocks"]:
                if block["type"] != 0:
                    continue
                for line in block["lines"]:
                    for span in line["spans"]:
                        if not span["text"].strip():
                            continue
                        blocks.append({
                            "text": span["text"],
                            "x": round(span["origin"][0], 1),
                            "y": round(span["origin"][1], 1),
                            "size": round(span["size"], 1),
                            "color": "#{:06x}".format(span["color"]),
                            "font": span["font"],
                            "flags": span["flags"],
                            "bbox": [round(v, 1) for v in span["bbox"]],
                        })

            pages.append({
                "width": round(width, 1),
                "height": round(height, 1),
                "blocks": blocks,
            })

        # Render achtergrondafbeeldingen MET tekst (overlay is transparant)
        for page_idx, page_data in enumerate(pages):
            page = doc[page_idx]
            mat = fitz.Matrix(120 / 72, 120 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("jpeg")
            page_data["image"] = base64.b64encode(img_bytes).decode("ascii")

        doc.close()
        logger.info(f"Klaar: {len(pages)} pagina's verwerkt")

        session_id = str(uuid.uuid4())
        sessions[session_id] = {"pdf_bytes": pdf_bytes, "pages": pages}

        return {
            "session_id": session_id,
            "pages": pages,
        }
    except Exception as e:
        doc.close()
        logger.error(f"Fout bij verwerken PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Fout bij verwerken: {str(e)}")


@app.post("/save/{session_id}")
async def save_pdf(session_id: str, request: Request):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = sessions[session_id]
    body = await request.json()
    edited_pages = body.get("pages", [])

    # Open het originele PDF document
    doc = fitz.open(stream=session["pdf_bytes"], filetype="pdf")

    for page_idx, edited_page in enumerate(edited_pages):
        if page_idx >= len(doc):
            break

        page = doc[page_idx]
        original_blocks = session["pages"][page_idx]["blocks"]

        # Vergelijk originele en bewerkte blokken
        for i, edited_block in enumerate(edited_page.get("blocks", [])):
            if i >= len(original_blocks):
                break

            orig = original_blocks[i]
            new_text = edited_block.get("text", "")

            # Bepaal de kleur (gebruik nieuwe kleur als die is meegegeven)
            new_color = edited_block.get("color", orig["color"])
            color_changed = new_color != orig["color"]

            if new_text != orig["text"] or color_changed:
                # Redact (verwijder) de oude tekst
                bbox = fitz.Rect(orig["bbox"])
                page.add_redact_annot(bbox, fill=(1, 1, 1))
                page.apply_redactions()

                # Converteer kleur naar RGB floats
                color_hex = _parse_color(new_color)
                r, g, b = (
                    int(color_hex[0:2], 16) / 255,
                    int(color_hex[2:4], 16) / 255,
                    int(color_hex[4:6], 16) / 255,
                )

                # Voeg de nieuwe tekst in op dezelfde positie
                if new_text.strip():
                    page.insert_text(
                        fitz.Point(orig["x"], orig["y"]),
                        new_text,
                        fontsize=orig["size"],
                        color=(r, g, b),
                    )

    pdf_output = doc.tobytes()
    doc.close()

    # Sessie opruimen — PDF data wordt direct uit geheugen verwijderd
    del sessions[session_id]

    return Response(
        content=pdf_output,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=bewerkt.pdf"},
    )
