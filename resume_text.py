from pypdf import PdfReader

RESUME_PATH = "private/resume.pdf"


def extract_resume_text(path=RESUME_PATH):
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


if __name__ == "__main__":
    text = extract_resume_text()
    print(f"{len(text)} characters extracted")
    print(text[:600])
