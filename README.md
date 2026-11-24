# Steam Meter Extractor


## The Problem

During my time as an intern with the CUNY Building Performance Lab, Steam usage was being tracked by manually reading an LCD meter from photos taken by a time-lapse camera. Each image had to be opened, the timestamp noted, the 8-digit reading typed by hand which made the process time-consuming and easy to get wrong

## The Solution

This tool processes a whole folder of images automatically:

1. Reads the **timestamp** burned into the bottom of each photo (OCR).
2. **Enhances** the image (contrast + sharpening) so the LCD digits are clearer.
3. Sends it to **Gemini Vision** to read the meter value (format `XXXXX.XXX`, in Mlbs).
4. **Cross-checks** the answer and flags anything doubtful. 
5. Writes a sorted, **color-coded Excel file** so a human only needs to review the flagged rows.

## Features

- **Batch processing** of `.jpg`, `.jpeg`, and `.png` files
- **Timestamp extraction** with OpenCV + Tesseract OCR; results are sorted chronologically
- **Image preprocessing**: CLAHE contrast enhancement on the luminance channel and unsharp-mask sharpening (no fixed crop, so it works if the camera shifts)
- **Two-vote verification**: each image is read twice by Gemini; if the reads agree it is trusted
- **Anomaly detection**: values outside the valid range, or a jump of more than 50% from the previous trusted reading, are flagged
- **Retry logic** with exponential backoff for API errors
- **Desktop GUI** (Tkinter) for non-technical users, with live log, progress bar, and Stop button
- **Command-line mode** for scripting

## Output

| Color | Meaning |
|-------|---------|
| White | Both reads agreed and there is no suspicious jump |
| Yellow | Reads disagreed (closest to previous value used) or a large jump from the last clean reading. **Review manually** |
| Red | Unreadable, no response, or out-of-range value |

Columns: `Date Time` | `Value (Mlbs)`

## Try It (Sample Images Included)

The `sample_images/` folder contains a small set of example meter photos so you can test the tool right away.

1. Install the requirements (see below) and get a free Gemini API key.
2. Run the GUI: `python3 steam_meter_gui.py`
3. Select the `sample_images` folder, paste your key, and click **Run Extraction**.
4. Compare your output with `docs/sample_output.xlsx` (the expected result). Small differences are normal, since AI reads can vary slightly.

Or from the command line:

```bash
python3 ImageRecognitionTool.py --input sample_images --api-key "YOUR_KEY" --output sample_results.xlsx
```

## Installation

```bash
git clone https://github.com/<your-username>/steam-meter-extractor.git
cd steam-meter-extractor
pip install -r requirements.txt
```

You also need the **Tesseract OCR** program installed on your computer (used for timestamps):

- macOS: `brew install tesseract`
- Windows: install from the [UB Mannheim builds](https://github.com/UB-Mannheim/tesseract/wiki) and add it to your PATH
- Linux: `sudo apt install tesseract-ocr`

And a free **Gemini API key** from [Google AI Studio](https://aistudio.google.com) (Get API Key).

## Usage

### Option 1: GUI

```bash
python3 steam_meter_gui.py
```

1. Select the folder of meter images
2. Paste your Gemini API key
3. Choose where to save the Excel file
4. Click **Run Extraction**

> `steam_meter_gui.py` and `ImageRecognitionTool.py` must be in the same folder.

### Option 2: Command line

```bash
python3 ImageRecognitionTool.py --input "path/to/images" --api-key "YOUR_KEY" --output "results.xlsx"
```

## How It Works

```
Images ──► OCR timestamp ──► Sort by time ──► Preprocess (CLAHE + sharpen)
                                                     │
                                                     ▼
Excel (color-coded) ◄── Validate / flag ◄── Gemini reads LCD x2
```

| Step | Technique |
|------|-----------|
| Timestamp | Crop bottom band, upscale 4x, threshold, Tesseract `--psm 7`, regex match |
| Enhancement | LAB color space, CLAHE on L channel, unsharp mask |
| Reading | Gemini 2.5 Flash with a prompt tuned for the `XXXXX.XXX` LCD format (e.g. 7 vs 9 reflections) |
| Validation | Range check (1,000 to 999,999), agreement tolerance of 0.5, jump check vs. last clean reading |

## Project Structure

```
steam-meter-extractor/
├── ImageRecognitionTool.py   # Core extraction engine (CLI)
├── steam_meter_gui.py        # Tkinter desktop launcher
├── requirements.txt
├── docs/                     # User manual, notes, screenshots
└── sample_images/            # Example meter photos for testing
```

