from main import main


def test_pdf_text_writing():
    result = main(
        pdf_path="sample.pdf",
        text="Hello World!",
        position=(100, 500),
        font_size=14,
        font_color=(1, 0, 0),  # Black
        font_name="F1",
        page_number=0,
        output_pdf_path="output_test.pdf",
    )
    print(result)


if __name__ == "__main__":
    test_pdf_text_writing()
