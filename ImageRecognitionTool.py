"""
ImageRecognitionTool — Steam Meter Extractor (Gemini Vision)
=============================================================
How to use:
  Run via the GUI:
      python3 steam_meter_gui.py

  Or directly from terminal:
      python3 ImageRecognitionTool.py --input "folder/of/images" --api-key "YOUR_KEY" --output "results.xlsx"

  Requirements (one-time install):
      pip install opencv-python openpyxl numpy google-generativeai pillow pytesseract

What it does:
  Reads each .jpg/.png image in the input folder, extracts the timestamp
  burned into the bottom of the image, and uses Google Gemini AI to read
  the numeric value displayed on the steam meter LCD. Results are saved
  to a color-coded Excel spreadsheet.
"""
import re, sys, argparse, time, io
from pathlib import Path
from datetime import datetime

try:
    import cv2
    import numpy as np
    import openpyxl
except ImportError as e:
    sys.exit(f"Missing package: {e}\nRun: pip install opencv-python openpyxl numpy")

try:
    from google import genai
    import PIL.Image
except ImportError:
    sys.exit("Run: pip install google-generativeai pillow")

try:
    import pytesseract
    TESSERACT_OK = True
except ImportError:
    TESSERACT_OK = False

SUPPORTED             = {".jpg", ".jpeg", ".png"}
TS_RE                 = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{2}:\d{2}:\d{2})")
VALUE_MIN             = 1000
VALUE_MAX             = 999999
MAX_RETRIES           = 3
VOTES                 = 2      # Gemini calls per image
AGREE_TOL             = 0.5    # two values count as "same" if they differ by less than this
SUSPICIOUS_JUMP_RATIO = 0.50

METER_PROMPT = """This is a photo of an industrial steam meter.
The meter has a circular face with an LCD display panel inside it showing a numeric reading.
The display shows a number in the format XXXXX.XXX (5 digits, a decimal point, then 3 digits).
The number represents a steam flow reading in thousands of pounds (Mlbs).

INSTRUCTIONS:
1. Zoom in on the LCD display in the center.
2. Read the 8-digit number. It MUST have 5 digits before the decimal and 3 digits after (XXXXX.XXX).
3. Look very closely at the digits immediately after the decimal point; reflections can make 7s look like 9s.
4. If you see '48327.798', ensure you don't misread it as '48327.980'.

Do not include any explanation, units, or extra text — just the number.
If you truly cannot read it, reply with exactly: UNREADABLE"""

# ── Gemini setup ──────────────────────────────────────────────────────────────

def setup_gemini(api_key):
    return genai.Client(api_key=api_key)

def ask_gemini(client, pil_image, prompt, retries=MAX_RETRIES):
    """Send a PIL image (already preprocessed) to Gemini and return raw text."""
    for attempt in range(retries):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, pil_image]
            )
            return response.text.strip()
        except Exception as e:
            msg = str(e)
            if "404" in msg or "NOT_FOUND" in msg:
                print(f"    Permanent Gemini error: {e}")
                return None
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"    Gemini error ({e}), retrying in {wait}s...")
                time.sleep(wait)
    return None

# ── Image preprocessing ───────────────────────────────────────────────────────

def preprocess_image(img_path):
    """
    Dynamically enhance contrast and sharpness on the full image before
    sending to Gemini. No fixed crop — works regardless of camera position.

    Steps:
      1. Load with OpenCV
      2. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
         on the luminance channel — boosts local contrast without blowing
         out highlights
      3. Sharpen with an unsharp mask
      4. Return as a PIL Image ready for Gemini
    """
    img_bgr = cv2.imread(str(img_path))
    if img_bgr is None:
        # Fall back to original if OpenCV can't read it
        return PIL.Image.open(str(img_path))

    # Convert to LAB so we only touch luminance
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # CLAHE on L channel
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_enhanced = clahe.apply(l)

    # Merge back and convert to BGR
    enhanced_lab = cv2.merge([l_enhanced, a, b])
    enhanced_bgr = cv2.cvtColor(enhanced_lab, cv2.COLOR_LAB2BGR)

    # Unsharp mask for sharpening
    blurred = cv2.GaussianBlur(enhanced_bgr, (0, 0), sigmaX=3)
    sharpened = cv2.addWeighted(enhanced_bgr, 1.5, blurred, -0.5, 0)

    # Convert BGR → RGB → PIL
    rgb = cv2.cvtColor(sharpened, cv2.COLOR_BGR2RGB)
    return PIL.Image.fromarray(rgb)

# ── Value parsing ─────────────────────────────────────────────────────────────

def parse_value(text):
    """
    Parse Gemini's raw text into a float.
    Returns (value_or_None, was_heavily_cleaned: bool)
    """
    if not text or "UNREADABLE" in text.upper():
        return None, False

    original = text.strip()
    cleaned  = (original
                .replace(",", ".")
                .replace("O", "0").replace("o", "0")
                .replace("I", "1").replace("l", "1"))

    substitutions_made = (cleaned != original.replace(",", "."))

    match = re.search(r"\d+\.\d+", cleaned)
    if not match:
        match = re.search(r"\d+", cleaned)
    if not match:
        return None, False

    matched_str = match.group()

    try:
        if "." in matched_str:
            value = float(matched_str)
        elif len(matched_str) >= 6:
            value = float(matched_str[:-3] + "." + matched_str[-3:])
            substitutions_made = True
        else:
            value = float(matched_str)
    except ValueError:
        return None, False

    if not (VALUE_MIN <= value <= VALUE_MAX):
        return None, False

    return value, substitutions_made


def is_large_jump(value, last_value, last_confidence):
    """Only flag a jump if the previous reading was a confident clean read (white).
    If the last reading was yellow or red, skip the jump check — baseline is unreliable."""
    if last_value is None or last_value == 0:
        return False
    if last_confidence != CONF_OK:
        return False
    return abs(value - last_value) / last_value > SUSPICIOUS_JUMP_RATIO

# ── Majority vote ─────────────────────────────────────────────────────────────

def majority_vote(client, pil_image, last_value, last_confidence):
    """
    Call Gemini 2 times.
    - If both agree (within AGREE_TOL) → use that value, CONF_OK (or CONF_SUSPICIOUS if big jump).
    - If they differ → pick the one closest to last_value, flag YELLOW.
    - If no valid values → CONF_FAILED.

    Returns (value_or_None, confidence, raw_votes)
    """
    raw_responses = []
    parsed_values = []

    for _ in range(VOTES):
        raw = ask_gemini(client, pil_image, METER_PROMPT)
        raw_responses.append(raw or "no response")
        val, _ = parse_value(raw)
        if val is not None:
            parsed_values.append(val)
        time.sleep(1)

    if not parsed_values:
        return None, CONF_FAILED, raw_responses

    if len(parsed_values) == 2 and abs(parsed_values[0] - parsed_values[1]) < AGREE_TOL:
        # Both agree
        value = parsed_values[0]
        conf  = CONF_SUSPICIOUS if is_large_jump(value, last_value, last_confidence) else CONF_OK
        return value, conf, raw_responses

    # Values differ (or only one valid) — pick closest to last_value
    if last_value is not None:
        best = min(parsed_values, key=lambda v: abs(v - last_value))
    else:
        best = parsed_values[0]
    return round(best, 3), CONF_SUSPICIOUS, raw_responses

# ── Timestamp extraction ──────────────────────────────────────────────────────

def get_timestamp(img_path):
    img = cv2.imread(str(img_path))
    if img is None:
        return None
    h, w  = img.shape[:2]
    band  = img[h-35:h, 0:w]
    gray  = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    big   = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, thresh = cv2.threshold(big, 80, 255, cv2.THRESH_BINARY)
    if TESSERACT_OK:
        try:
            text = pytesseract.image_to_string(thresh, config="--psm 7")
            m    = TS_RE.search(text)
            if m:
                return f"{m.group(1)} {m.group(2)}"
        except Exception:
            pass
    return None

# ── Confidence levels ─────────────────────────────────────────────────────────

CONF_OK         = "ok"
CONF_SUSPICIOUS = "suspect"
CONF_FAILED     = "failed"

# ── Excel output ──────────────────────────────────────────────────────────────

def write_excel(rows, output_path):
    from openpyxl.styles import Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Steam Meter Data"

    headers = ["Date Time", "Value (Mlbs)"]
    widths  = [25, 18]
    for col, (h, w) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font = Font(bold=True)
        ws.column_dimensions[cell.column_letter].width = w

    red_fill    = PatternFill("solid", fgColor="FFCCCC")
    yellow_fill = PatternFill("solid", fgColor="FFFF99")

    for i, (dt_str, val, confidence) in enumerate(rows, start=2):
        dt_obj = None
        if dt_str:
            try:
                dt_obj = datetime.strptime(dt_str, "%m/%d/%Y %H:%M:%S")
            except ValueError:
                pass

        fill = (red_fill    if confidence == CONF_FAILED     else
                yellow_fill if confidence == CONF_SUSPICIOUS else None)

        c1 = ws.cell(row=i, column=1, value=dt_obj or dt_str or "?")
        if dt_obj:
            c1.number_format = "MM/DD/YYYY HH:MM:SS"
        if fill:
            c1.fill = fill

        c2 = ws.cell(row=i, column=2)
        if val is not None:
            c2.value = round(val, 3)
            c2.number_format = "#,##0.000"
        if fill:
            c2.fill = fill

    wb.save(output_path)
    print(f"\nSaved {len(rows)} rows → {output_path}")
    print("  🔴 Red    = truly unreadable (UNREADABLE / no response / out of range)")
    print("  🟡 Yellow = all 3 votes differed (closest to last used) OR big jump from last reading")
    print("  ✅ White  = 2+ votes agreed, no large jump")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",   "-i", required=True)
    parser.add_argument("--api-key", "-k", required=True)
    parser.add_argument("--output",  "-o", default="output.xlsx")
    parser.add_argument("--debug",   action="store_true")
    args = parser.parse_args()

    input_dir   = Path(args.input)
    output_path = Path(args.output)

    if not input_dir.is_dir():
        sys.exit(f"Not a folder: {input_dir}")

    images = sorted([p for p in input_dir.iterdir() if p.suffix.lower() in SUPPORTED])
    if not images:
        sys.exit(f"No images found in {input_dir}")

    print("Connecting to Gemini...")
    client = setup_gemini(args.api_key)
    print(f"Ready. Processing {len(images)} images (2 Gemini calls each)...\n")

    # ── Pass 1: timestamps ────────────────────────────────────────────────────
    print("Reading timestamps...")
    timestamps = {}
    for i, p in enumerate(images, 1):
        ts = get_timestamp(p)
        timestamps[p] = ts
        print(f"  [{i:>4}/{len(images)}] {p.name:<45} ts={ts or '?'}")

    def sort_key(p):
        ts = timestamps.get(p)
        if ts:
            try:
                return datetime.strptime(ts, "%m/%d/%Y %H:%M:%S")
            except ValueError:
                pass
        return datetime.max

    sorted_images = sorted(images, key=sort_key)

    # ── Pass 2: meter values ──────────────────────────────────────────────────
    print("\nReading meter values with Gemini...\n")
    final_rows = []
    last_value = None
    last_confidence = None
    n_ok = n_yellow = n_fail = 0

    for p in sorted_images:
        ts = timestamps.get(p)

        # Preprocess image once, reuse the PIL image for all 3 votes
        pil_image = preprocess_image(p)

        value, confidence, raw_votes = majority_vote(client, pil_image, last_value, last_confidence)

        if confidence == CONF_OK:
            n_ok += 1
            last_value = value
            last_confidence = CONF_OK
            status = "✓"
        elif confidence == CONF_SUSPICIOUS:
            n_yellow += 1
            last_value = value
            last_confidence = CONF_SUSPICIOUS
            status = "?"
        else:
            n_fail += 1
            status = "✗"

        label      = {"ok": "OK", "suspect": "YELLOW", "failed": "RED"}[confidence]
        votes_str  = " | ".join(raw_votes)
        print(f"  {status} [{label:<6}] {ts or '?':<22}  votes=[{votes_str}]  →  {value if value is not None else 'FAILED'}")
        final_rows.append((ts, value, confidence))

        time.sleep(1)  # pause between images (votes already have their own pause)

    write_excel(final_rows, output_path)

    total = len(final_rows)
    print(f"\n{'='*55}")
    print(f"Summary:")
    print(f"  Total images  : {total}")
    print(f"  ✅ Clean reads : {n_ok}  ({100*n_ok//max(total,1)}%)")
    print(f"  🟡 Suspicious  : {n_yellow}  ({100*n_yellow//max(total,1)}%)")
    print(f"  🔴 Failed      : {n_fail}  ({100*n_fail//max(total,1)}%)")
    print(f"  Output        : {output_path}")

if __name__ == "__main__":
    main()
