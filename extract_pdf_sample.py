import sys
import os

try:
    from pypdf import PdfReader
except ImportError:
    print("Please install pypdf by running: pip install pypdf")
    sys.exit(1)

pdf_path = "data/runbooks/database-error-messages.pdf"

if not os.path.exists(pdf_path):
    print(f"Error: Could not find {pdf_path}")
    sys.exit(1)

print(f"Analyzing PDF: {pdf_path}")
reader = PdfReader(pdf_path)
total_pages = len(reader.pages)
print(f"Total Pages: {total_pages}")

print("\n--- SAMPLE EXTRACT (PAGE 10) ---")
# Let's peek at page 10 to skip the title pages and index
try:
    text = reader.pages[10].extract_text()
    print(text[:1000]) # Print first 1000 characters
except Exception as e:
    print(f"Error reading page: {e}")

print("\n--- SAMPLE EXTRACT (PAGE 25) ---")
try:
    text = reader.pages[25].extract_text()
    print(text[:1000])
except Exception as e:
    print(f"Error reading page: {e}")
