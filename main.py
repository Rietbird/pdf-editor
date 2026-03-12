import base64
import io
import uuid

import fitz  # PyMuPDF
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# In-memory session store
sessions: dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "rb") as f:
        return HTMLResponse(content=f.read())


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    pages = []
    for page in doc:
        # Haal tekst blokken op met positie en stijl VOORDAT we tekst verwijderen
        text_dict = page.get_text("dict")
        width = page.rect.width
        height = page.rect.height

        blocks = []
        for block in text_dict["blocks"]:
            if block["type"] != 0:  # Alleen tekst blokken
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
                        "flags": span["flags"],  # bold=16, italic=2
                        "bbox": [round(v, 1) for v in span["bbox"]],
                    })

        pages.append({
            "width": round(width, 1),
            "height": round(height, 1),
            "blocks": blocks,
        })

    # Render achtergrondafbeeldingen ZONDER tekst:
    # Gebruik redaction op een kopie van het hele document
    tmp_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page_idx, page_data in enumerate(pages):
        tmp_page = tmp_doc[page_idx]
        text_dict = tmp_page.get_text("dict")
        for block in text_dict["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if span["text"].strip():
                        tmp_page.add_redact_annot(fitz.Rect(span["bbox"]))
        tmp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        mat = fitz.Matrix(150 / 72, 150 / 72)
        pix = tmp_page.get_pixmap(matrix=mat)
        img_bytes_png = pix.tobytes("png")
        page_data["image"] = base64.b64encode(img_bytes_png).decode("ascii")

    tmp_doc.close()
    doc.close()

    session_id = str(uuid.uuid4())
    sessions[session_id] = {"pdf_bytes": pdf_bytes, "pages": pages}

    # Stuur alles behalve pdf_bytes naar de frontend
    return {
        "session_id": session_id,
        "pages": pages,
    }


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

            if new_text != orig["text"]:
                # Redact (verwijder) de oude tekst
                bbox = fitz.Rect(orig["bbox"])
                page.add_redact_annot(bbox, fill=(1, 1, 1))
                page.apply_redactions()

                # Voeg de nieuwe tekst in op dezelfde positie
                fontsize = orig["size"]
                color_hex = orig["color"].lstrip("#")
                r, g, b = (
                    int(color_hex[0:2], 16) / 255,
                    int(color_hex[2:4], 16) / 255,
                    int(color_hex[4:6], 16) / 255,
                )

                page.insert_text(
                    fitz.Point(orig["x"], orig["y"]),
                    new_text,
                    fontsize=fontsize,
                    color=(r, g, b),
                )

    pdf_output = doc.tobytes()
    doc.close()

    return Response(
        content=pdf_output,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=bewerkt.pdf"},
    )
